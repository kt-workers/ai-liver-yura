"""#332 MemoryRepositoryPortを満たすSQLite adapter。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from threading import RLock
from typing import Literal

from app.domain.memory.contracts import (
    MemoryRecord,
    MemoryRelation,
    MemoryRelationKind,
)
from app.domain.memory.repository import MemoryRepositorySnapshot

from .contracts import PersistenceError, PersistenceFailureCode
from .memory_codec import decode_memory_record, encode_memory_record


class SqliteMemoryRepository:
    """#332のexact revisionとrelation transactionを安全なJSONで保存する。"""

    storage_schema_version = 1

    def __init__(self, database_path: str) -> None:
        self._lock = RLock()
        try:
            self._connection = sqlite3.connect(database_path, check_same_thread=False)
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._migrate()
        except sqlite3.Error as error:
            raise PersistenceError(
                PersistenceFailureCode.CONNECTION_FAILED,
                "Memory storageへ接続できません",
            ) from error

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def get(self, memory_id: str) -> MemoryRecord | None:
        row = self._query_one(
            "SELECT payload FROM memory_records WHERE memory_id = ?",
            (memory_id,),
        )
        return None if row is None else decode_memory_record(row[0])

    def list_records(self) -> tuple[MemoryRecord, ...]:
        return tuple(
            decode_memory_record(row[0])
            for row in self._query_all("SELECT payload FROM memory_records ORDER BY memory_id", ())
        )

    def list_relations(self) -> tuple[MemoryRelation, ...]:
        return tuple(
            _decode_relation(row[0])
            for row in self._query_all(
                "SELECT payload FROM memory_relations ORDER BY relation_id",
                (),
            )
        )

    def snapshot(self) -> MemoryRepositorySnapshot:
        return MemoryRepositorySnapshot(self.list_records(), self.list_relations())

    def save_record(self, record: MemoryRecord, *, expected_revision: int | None) -> bool:
        with self._transaction() as cursor:
            previous = self._revision(cursor, record.memory_id)
            if previous is None:
                if expected_revision is not None or record.revision != 0:
                    return False
                cursor.execute(
                    "INSERT INTO memory_records VALUES (?, ?, ?)",
                    (record.memory_id, record.revision, encode_memory_record(record)),
                )
                return True
            if expected_revision != previous or record.revision != previous + 1:
                return False
            cursor.execute(
                "UPDATE memory_records SET revision = ?, payload = ? WHERE memory_id = ?",
                (record.revision, encode_memory_record(record), record.memory_id),
            )
            return True

    def save_relation(self, relation: MemoryRelation) -> bool:
        with self._transaction() as cursor:
            exists = self._relation_exists(cursor, relation.relation_id)
            if exists or not self._relation_targets_exist(cursor, relation):
                return False
            self._insert_relation(cursor, relation)
            return True

    def commit_related(
        self,
        record: MemoryRecord,
        relation: MemoryRelation,
        *,
        target_update: MemoryRecord | None,
        expected_target_revision: int | None,
    ) -> bool:
        with self._transaction() as cursor:
            if self._revision(cursor, record.memory_id) is not None or self._relation_exists(
                cursor, relation.relation_id
            ):
                return False
            if not self._target_is_current(cursor, target_update, expected_target_revision):
                return False
            existing_ids = {record.memory_id}
            if target_update is not None:
                existing_ids.add(target_update.memory_id)
            if not self._relation_targets_exist(cursor, relation, existing_ids):
                return False
            cursor.execute(
                "INSERT INTO memory_records VALUES (?, ?, ?)",
                (record.memory_id, record.revision, encode_memory_record(record)),
            )
            if target_update is not None:
                cursor.execute(
                    "UPDATE memory_records SET revision = ?, payload = ? WHERE memory_id = ?",
                    (
                        target_update.revision,
                        encode_memory_record(target_update),
                        target_update.memory_id,
                    ),
                )
            self._insert_relation(cursor, relation)
            return True

    def _migrate(self) -> None:
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS persistence_meta "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS memory_records "
            "(memory_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL)"
        )
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS memory_relations "
            "(relation_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
        row = self._connection.execute(
            "SELECT value FROM persistence_meta WHERE key = 'memory_schema_version'"
        ).fetchone()
        if row is not None and int(row[0]) > self.storage_schema_version:
            raise PersistenceError(
                PersistenceFailureCode.INCOMPATIBLE_STORAGE_VERSION,
                "Memory storage schemaが新しすぎます",
            )
        self._connection.execute(
            "INSERT OR REPLACE INTO persistence_meta VALUES ('memory_schema_version', ?)",
            (str(self.storage_schema_version),),
        )
        self._connection.commit()

    def _query_one(self, query: str, parameters: tuple[str, ...]) -> tuple[str] | None:
        with self._lock:
            row = self._connection.execute(query, parameters).fetchone()
        return None if row is None else (row[0],)

    def _query_all(self, query: str, parameters: tuple[str, ...]) -> tuple[tuple[str], ...]:
        with self._lock:
            rows = self._connection.execute(query, parameters).fetchall()
        return tuple((row[0],) for row in rows)

    def _transaction(self) -> _Transaction:
        return _Transaction(self._connection, self._lock)

    @staticmethod
    def _revision(cursor: sqlite3.Cursor, memory_id: str) -> int | None:
        row = cursor.execute(
            "SELECT revision FROM memory_records WHERE memory_id = ?",
            (memory_id,),
        ).fetchone()
        return None if row is None else row[0]

    @staticmethod
    def _relation_exists(cursor: sqlite3.Cursor, relation_id: str) -> bool:
        return (
            cursor.execute(
                "SELECT 1 FROM memory_relations WHERE relation_id = ?",
                (relation_id,),
            ).fetchone()
            is not None
        )

    def _relation_targets_exist(
        self,
        cursor: sqlite3.Cursor,
        relation: MemoryRelation,
        new_memory_ids: set[str] | None = None,
    ) -> bool:
        return all(
            memory_id in (new_memory_ids or set())
            or self._revision(cursor, memory_id) is not None
            for memory_id in (relation.left_memory_id, relation.right_memory_id)
        )

    def _target_is_current(
        self,
        cursor: sqlite3.Cursor,
        target_update: MemoryRecord | None,
        expected_revision: int | None,
    ) -> bool:
        if target_update is None:
            return expected_revision is None
        previous = self._revision(cursor, target_update.memory_id)
        return (
            previous is not None
            and expected_revision == previous
            and target_update.revision == previous + 1
        )

    @staticmethod
    def _insert_relation(cursor: sqlite3.Cursor, relation: MemoryRelation) -> None:
        cursor.execute(
            "INSERT INTO memory_relations VALUES (?, ?)",
            (relation.relation_id, _encode_relation(relation)),
        )


class _Transaction:
    def __init__(self, connection: sqlite3.Connection, lock: RLock) -> None:
        self._connection = connection
        self._lock = lock

    def __enter__(self) -> sqlite3.Cursor:
        self._lock.acquire()
        self._connection.execute("BEGIN IMMEDIATE")
        return self._connection.cursor()

    def __exit__(
        self,
        exception_type: object,
        exception: object,
        traceback: object,
    ) -> Literal[False]:
        try:
            if exception_type is None:
                self._connection.commit()
            else:
                self._connection.rollback()
        finally:
            self._lock.release()
        return False


def _encode_relation(relation: MemoryRelation) -> str:
    return json.dumps(
        {
            "relation_id": relation.relation_id,
            "left_memory_id": relation.left_memory_id,
            "right_memory_id": relation.right_memory_id,
            "kind": relation.kind.value,
            "evidence_refs": list(relation.evidence_refs),
            "created_at": relation.created_at.isoformat(),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _decode_relation(raw: str) -> MemoryRelation:
    try:
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError
        created_at = datetime.fromisoformat(value["created_at"])
        return MemoryRelation(
            value["relation_id"],
            value["left_memory_id"],
            value["right_memory_id"],
            MemoryRelationKind(value["kind"]),
            tuple(value["evidence_refs"]),
            created_at,
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise PersistenceError(
            PersistenceFailureCode.CORRUPT_RECORD,
            "Memory relationが不正です",
        ) from error
