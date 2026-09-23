"""RepositoryのMemory ID別同期metadata。意味内容や複製Stateは保持しない。"""

from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from threading import Lock
from typing import Concatenate, ParamSpec, Protocol, TypeVar
from weakref import WeakKeyDictionary, WeakSet

from app.domain.contracts.finalization import (
    AuthorityFinalizationParticipant,
    FinalizationError,
    FinalizationFailure,
)
from app.domain.memory.contracts import (
    MemoryKind,
    MemoryRecord,
    MemoryRelation,
    MemoryRetrievalQuery,
)


class _MemoryCell:
    def __init__(self) -> None:
        self.participant = AuthorityFinalizationParticipant(self, "MemoryStoreAuthority", 55)


@dataclass(frozen=True, slots=True)
class _RetrievalScope:
    kind: MemoryKind
    subject_ref: str | None
    temporal_scope_ref: str | None
    observed_at: datetime | None

    @classmethod
    def from_record(cls, record: MemoryRecord) -> "_RetrievalScope":
        return cls(
            record.kind,
            record.content.subject_ref,
            record.content.temporal_scope_ref,
            record.temporal.observed_at,
        )

    def matches(self, query: MemoryRetrievalQuery) -> bool:
        """eligibilityで現在除外された候補も、将来の変化の対象に含める。"""
        return (
            (not query.memory_kinds or self.kind in query.memory_kinds)
            and (not query.subject_refs or self.subject_ref in query.subject_refs)
            and (
                query.temporal_scope_ref is None
                or self.temporal_scope_ref == query.temporal_scope_ref
            )
            and (
                query.observed_from is None
                or (self.observed_at is not None and self.observed_at >= query.observed_from)
            )
            and (
                query.observed_until is None
                or (self.observed_at is not None and self.observed_at <= query.observed_until)
            )
        )


class _RetrievalParticipant(AuthorityFinalizationParticipant):
    def __init__(self) -> None:
        super().__init__(self, "MemoryRetrievalAuthority", 56)


class MemoryIndexSynchronizationPort(Protocol):
    """正本mutationと派生indexの同期metadataを接続する。"""

    def begin_canonical_mutation(self, memory_ids: frozenset[str]) -> object: ...

    def end_canonical_mutation(self, marker: object) -> None: ...


class MemoryFinalizationRegistry:
    def __init__(self) -> None:
        self._indexes: WeakSet[MemoryIndexSynchronizationPort] = WeakSet()
        self._cells: dict[str, _MemoryCell] = {}
        self._registry_lock = Lock()
        self._retrievals: WeakKeyDictionary[_RetrievalParticipant, MemoryRetrievalQuery] = (
            WeakKeyDictionary()
        )
        self._pending_retrieval_mutations: dict[object, tuple[_RetrievalScope, ...]] = {}

    def register_index(self, index: MemoryIndexSynchronizationPort) -> None:
        with self._registry_lock:
            if self._pending_retrieval_mutations:
                raise FinalizationError(FinalizationFailure.PARTICIPANT_BUSY)
            self._indexes.add(index)

    def participant(self, memory_id: str) -> AuthorityFinalizationParticipant:
        with self._registry_lock:
            cell = self._cells.get(memory_id)
            if cell is None:
                cell = _MemoryCell()
                self._cells[memory_id] = cell
            return cell.participant

    def retrieval_participant(
        self, query: MemoryRetrievalQuery
    ) -> AuthorityFinalizationParticipant:
        participant = _RetrievalParticipant()
        with self._registry_lock:
            if any(
                scope.matches(query)
                for scopes in self._pending_retrieval_mutations.values()
                for scope in scopes
            ):
                raise FinalizationError(FinalizationFailure.PARTICIPANT_BUSY)
            self._retrievals[participant] = query
        return participant

    @contextmanager
    def retrieval_mutation(self, records: tuple[MemoryRecord, ...]) -> Iterator[None]:
        """ID境界内で旧・新の候補範囲を登録してから、検索境界を全順序で取得する。"""
        scopes = tuple(_RetrievalScope.from_record(record) for record in records)
        marker = object()
        with self._registry_lock:
            self._pending_retrieval_mutations[marker] = scopes
            indexes = tuple(self._indexes)
            participants = sorted(
                (
                    p
                    for p, query in self._retrievals.items()
                    if any(scope.matches(query) for scope in scopes)
                ),
                key=lambda p: p.order_key,
            )
        try:
            with ExitStack() as stack:
                for participant in participants:
                    stack.enter_context(participant.mutation())
                ids = frozenset(record.memory_id for record in records)
                for index in indexes:
                    index_marker = index.begin_canonical_mutation(ids)
                    stack.callback(index.end_canonical_mutation, index_marker)
                yield
        finally:
            with self._registry_lock:
                del self._pending_retrieval_mutations[marker]

    @contextmanager
    def mutation(self, memory_ids: set[str]) -> Iterator[None]:
        participants = sorted((self.participant(i) for i in memory_ids), key=lambda p: p.order_key)
        with ExitStack() as stack:
            for participant in participants:
                stack.enter_context(participant.mutation())
            yield


# storageを再接続しても、発行済みtokenの同期metadataを失わない。
_namespaces: dict[tuple[object, ...], MemoryFinalizationRegistry] = {}
_namespaces_lock = Lock()


def shared_memory_registry(namespace: tuple[object, ...]) -> MemoryFinalizationRegistry:
    with _namespaces_lock:
        if namespace not in _namespaces:
            _namespaces[namespace] = MemoryFinalizationRegistry()
        return _namespaces[namespace]


class GuardedMemoryRepository(Protocol):
    semantic_guards: MemoryFinalizationRegistry

    def get(self, memory_id: str) -> MemoryRecord | None: ...


A = TypeVar("A", bound=GuardedMemoryRepository)
P = ParamSpec("P")
T = TypeVar("T")


def memory_mutation(method: Callable[Concatenate[A, P], T]) -> Callable[Concatenate[A, P], T]:
    @wraps(method)
    def guarded(self: A, /, *args: P.args, **kwargs: P.kwargs) -> T:
        ids: set[str] = set()
        for value in (*args, *kwargs.values()):
            if isinstance(value, MemoryRecord):
                ids.add(value.memory_id)
            elif isinstance(value, MemoryRelation):
                ids.update((value.left_memory_id, value.right_memory_id))
        if not ids:
            raise ValueError("Memory mutationの対象IDがありません")
        with self.semantic_guards.mutation(ids):
            previous = tuple(record for mid in sorted(ids) if (record := self.get(mid)) is not None)
            proposed = tuple(
                value for value in (*args, *kwargs.values()) if isinstance(value, MemoryRecord)
            )
            with self.semantic_guards.retrieval_mutation(previous + proposed):
                return method(self, *args, **kwargs)

    return guarded
