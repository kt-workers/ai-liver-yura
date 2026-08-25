from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from app.domain.memory.contracts import MemoryRecord, MemoryRelation


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

    def save_relation(self, relation: MemoryRelation) -> bool:
        if not self.available:
            raise RuntimeError("repository unavailable")
        if relation.relation_id in self._relations:
            return False
        self._relations[relation.relation_id] = relation
        return True

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

    def related_ids(self, query: str, *, limit: int) -> Iterable[str]: ...
