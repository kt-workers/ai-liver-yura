from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from threading import Lock
from typing import Protocol, runtime_checkable

from app.domain.contracts.finalization import (
    AuthorityFinalizationParticipant,
    AuthorityGenerationToken,
    FinalizationError,
    FinalizationFailure,
)
from app.domain.memory.contracts import MemoryRecord, MemoryRelation
from app.domain.memory.finalization import MemoryFinalizationRegistry, memory_mutation
from app.domain.memory.ranking import MemorySemanticRelevance


@dataclass(frozen=True, slots=True)
class MemoryRepositorySnapshot:
    """同一時点の正本record/relation読取り結果。"""

    records: tuple[MemoryRecord, ...]
    relations: tuple[MemoryRelation, ...]


class MemoryRepositoryPort(Protocol):
    """正本Memoryの永続化境界。実装は原子的な期待revision検査を提供する。"""

    def get(self, memory_id: str) -> MemoryRecord | None: ...

    def list_records(self) -> tuple[MemoryRecord, ...]: ...

    def list_relations(self) -> tuple[MemoryRelation, ...]: ...

    def snapshot(self) -> MemoryRepositorySnapshot: ...

    def save_record(self, record: MemoryRecord, *, expected_revision: int | None) -> bool: ...

    def save_relation(self, relation: MemoryRelation) -> bool: ...

    def commit_related(
        self,
        record: MemoryRecord,
        relation: MemoryRelation,
        *,
        target_update: MemoryRecord | None,
        expected_target_revision: int | None,
    ) -> bool: ...


class InMemoryMemoryRepository:
    """単体検証用の同期・局所的なMemory repository実装。"""

    def __init__(self) -> None:
        self.semantic_guards = MemoryFinalizationRegistry()
        self._records: dict[str, MemoryRecord] = {}
        self._relations: dict[str, MemoryRelation] = {}
        self.available = True

    def get(self, memory_id: str) -> MemoryRecord | None:
        if not self.available:
            raise RuntimeError("repository unavailable")
        return self._records.get(memory_id)

    def list_records(self) -> tuple[MemoryRecord, ...]:
        if not self.available:
            raise RuntimeError("repository unavailable")
        return tuple(self._records[key] for key in sorted(self._records))

    def list_relations(self) -> tuple[MemoryRelation, ...]:
        if not self.available:
            raise RuntimeError("repository unavailable")
        return tuple(self._relations[key] for key in sorted(self._relations))

    def snapshot(self) -> MemoryRepositorySnapshot:
        if not self.available:
            raise RuntimeError("repository unavailable")
        return MemoryRepositorySnapshot(self.list_records(), self.list_relations())

    @memory_mutation
    def save_record(self, record: MemoryRecord, *, expected_revision: int | None) -> bool:
        if not self.available:
            raise RuntimeError("repository unavailable")
        existing = self._records.get(record.memory_id)
        if existing is None:
            if expected_revision is not None or record.revision != 0:
                return False
        elif expected_revision != existing.revision or record.revision != existing.revision + 1:
            return False
        self._records[record.memory_id] = record
        return True

    @memory_mutation
    def save_relation(self, relation: MemoryRelation) -> bool:
        if not self.available:
            raise RuntimeError("repository unavailable")
        if relation.relation_id in self._relations:
            return False
        self._relations[relation.relation_id] = relation
        return True

    @memory_mutation
    def commit_related(
        self,
        record: MemoryRecord,
        relation: MemoryRelation,
        *,
        target_update: MemoryRecord | None,
        expected_target_revision: int | None,
    ) -> bool:
        """related write全体を事前検査後に一括反映する。"""
        if not self.available:
            raise RuntimeError("repository unavailable")
        if record.memory_id in self._records or relation.relation_id in self._relations:
            return False
        if target_update is None:
            if expected_target_revision is not None:
                return False
        else:
            target = self._records.get(target_update.memory_id)
            if (
                target is None
                or expected_target_revision != target.revision
                or target_update.revision != target.revision + 1
            ):
                return False
        self._records[record.memory_id] = record
        self._relations[relation.relation_id] = relation
        if target_update is not None:
            self._records[target_update.memory_id] = target_update
        return True


class MemorySemanticIndexPort(Protocol):
    """派生検索index。正本identity又はwrite dispositionを決定しない。"""

    def upsert(self, record: MemoryRecord) -> None: ...

    def related_scores(
        self, query: str, *, limit: int
    ) -> Iterable[MemorySemanticRelevance]: ...


@runtime_checkable
class RebuildableMemorySemanticIndexPort(MemorySemanticIndexPort, Protocol):
    """正本snapshotで派生indexを全置換し、削除済みentryも取り除く能力。"""

    def rebuild(self, records: tuple[MemoryRecord, ...]) -> None: ...


class MemorySemanticIndexState(str, Enum):
    CURRENT = "CURRENT"
    UPDATE_PENDING = "UPDATE_PENDING"
    DEGRADED = "DEGRADED"


class FinalizableMemorySemanticIndex:
    """同期状態と世代を所有し、遅いDB/index処理には共通lockを保持しない。"""

    def __init__(self, index: MemorySemanticIndexPort) -> None:
        self._index = index
        self._repository: MemoryRepositoryPort | None = None
        self._registry: MemoryFinalizationRegistry | None = None
        self._pending_canonical: dict[object, frozenset[str]] = {}
        self._dirty: dict[str, int] = {}
        self._update_locks: dict[str, Lock] = {}
        self._active_updates = 0
        self._repairing = False
        self._repair_required = True
        self._serial = 0
        self._canonical_revision = 0
        self.finalization_participant = AuthorityFinalizationParticipant(
            self, "MemorySemanticIndex", 58
        )

    def bind(self, repository: MemoryRepositoryPort) -> None:
        """構成時に一つの正本namespaceへ登録する。同期済みとは推測しない。"""
        registry = getattr(repository, "semantic_guards", None)
        if not isinstance(registry, MemoryFinalizationRegistry):
            raise FinalizationError(FinalizationFailure.PARTICIPANT_UNSUPPORTED)
        if self._registry is not None:
            if self._registry is not registry:
                raise ValueError("semantic indexは別の正本namespaceへ再登録できません")
            return
        registry.register_index(self)
        self._repository = repository
        self._registry = registry

    @property
    def synchronization_state(self) -> MemorySemanticIndexState:
        with self.finalization_participant:
            return self._state()

    def _state(self) -> MemorySemanticIndexState:
        if self._pending_canonical or self._active_updates or self._repairing:
            return MemorySemanticIndexState.UPDATE_PENDING
        if self._repair_required or self._dirty:
            return MemorySemanticIndexState.DEGRADED
        return MemorySemanticIndexState.CURRENT

    def current_token(self) -> AuthorityGenerationToken:
        with self.finalization_participant:
            state = self._state()
            if state is not MemorySemanticIndexState.CURRENT:
                raise FinalizationError(
                    FinalizationFailure.PARTICIPANT_BUSY
                    if state is MemorySemanticIndexState.UPDATE_PENDING
                    else FinalizationFailure.PARTICIPANT_UNAVAILABLE
                )
            return self.finalization_participant.token()

    def begin_canonical_mutation(self, memory_ids: frozenset[str]) -> object:
        marker = object()
        with self.finalization_participant.mutation():
            self._serial += 1
            self._canonical_revision += 1
            self._pending_canonical[marker] = memory_ids
            for memory_id in memory_ids:
                self._dirty[memory_id] = self._serial
        return marker

    def end_canonical_mutation(self, marker: object) -> None:
        with self.finalization_participant.mutation():
            del self._pending_canonical[marker]

    def upsert(self, record: MemoryRecord) -> None:
        with self.finalization_participant:
            lock = self._update_locks.setdefault(record.memory_id, Lock())
        # 同じIDの古い更新が新しいindex内容を後から上書きしない。
        with lock:
            with self.finalization_participant.mutation():
                if self._repairing or any(
                    record.memory_id in ids for ids in self._pending_canonical.values()
                ):
                    self._repair_required = True
                    raise RuntimeError("semantic indexの同期処理が競合しています")
                self._serial += 1
                serial = self._serial
                self._dirty[record.memory_id] = serial
                self._active_updates += 1
            success = False
            try:
                repository = self._repository
                if repository is None or repository.get(record.memory_id) != record:
                    raise RuntimeError("semantic index更新の入力が現在の正本と一致しません")
                self._index.upsert(record)
                success = True
            finally:
                with self.finalization_participant.mutation():
                    self._active_updates -= 1
                    synchronized = success and self._dirty.get(record.memory_id) == serial
                    if synchronized:
                        del self._dirty[record.memory_id]
                    else:
                        self._repair_required = True
            if not synchronized:
                raise RuntimeError("semantic index更新中に正本が変更されました")

    def rebuild(self) -> None:
        """明示要求による全置換だけで、障害後の同期を回復する。"""
        with self.finalization_participant.mutation():
            if self._pending_canonical or self._active_updates or self._repairing:
                raise RuntimeError("semantic indexの修復開始時に更新が残っています")
            self._repairing = True
            self._repair_required = True
            revision = self._canonical_revision
        success = False
        try:
            repository = self._repository
            if repository is None or not isinstance(
                self._index, RebuildableMemorySemanticIndexPort
            ):
                raise RuntimeError("semantic indexの明示修復能力がありません")
            self._index.rebuild(repository.snapshot().records)
            success = True
        finally:
            with self.finalization_participant.mutation():
                self._repairing = False
                coherent = success and revision == self._canonical_revision
                if coherent:
                    self._dirty.clear()
                    self._repair_required = False
        if not coherent:
            raise RuntimeError("semantic indexの修復中に正本が変更されました")

    def related_scores(self, query: str, *, limit: int) -> tuple[MemorySemanticRelevance, ...]:
        with self.finalization_participant:
            if self._state() is not MemorySemanticIndexState.CURRENT:
                raise RuntimeError("semantic indexが正本と同期していません")
            token = self.finalization_participant.token()
        result = tuple(self._index.related_scores(query, limit=limit))
        with self.finalization_participant:
            if (
                self._state() is not MemorySemanticIndexState.CURRENT
                or token != self.finalization_participant.token()
            ):
                raise RuntimeError("semantic indexの読取中に同期状態が変更されました")
        return result
