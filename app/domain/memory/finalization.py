"""RepositoryのMemory ID別同期metadata。意味内容や複製Stateは保持しない。"""

from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from functools import wraps
from threading import Lock
from typing import Concatenate, ParamSpec, Protocol, TypeVar

from app.domain.contracts.finalization import AuthorityFinalizationParticipant
from app.domain.memory.contracts import MemoryRecord, MemoryRelation


class _MemoryCell:
    def __init__(self) -> None:
        self.participant = AuthorityFinalizationParticipant(self, "MemoryStoreAuthority", 55)


class MemoryFinalizationRegistry:
    def __init__(self) -> None:
        self._cells: dict[str, _MemoryCell] = {}
        self._registry_lock = Lock()

    def participant(self, memory_id: str) -> AuthorityFinalizationParticipant:
        with self._registry_lock:
            cell = self._cells.get(memory_id)
            if cell is None:
                cell = _MemoryCell()
                self._cells[memory_id] = cell
            return cell.participant

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
            return method(self, *args, **kwargs)

    return guarded
