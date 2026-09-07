"""本番PostgreSQLで記憶・版・関係を同じ取引として保存する。"""

from collections.abc import Callable
from hashlib import sha256

from app.domain.contracts.common import require_revision
from app.domain.memory.contracts import MemoryRecord, MemoryRelation
from app.domain.memory.repository import MemoryRepositorySnapshot

from .contracts import PersistenceError, PersistenceFailureCode
from .memory_codec import decode_memory_record, encode_memory_record
from .postgresql_connection import PostgresConnection, PostgresDatabase
from .relation_codec import decode_relation, encode_relation


class PostgresMemoryRepository:
    """共有接続群を借用する記憶保存先。接続群の終了は構成側が所有する。"""

    storage_schema_version = 1

    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def migrate(self) -> None:
        try:
            with self._database.transaction() as c:
                c.execute("SELECT pg_advisory_xact_lock(1498763841)")
                c.execute("CREATE SCHEMA IF NOT EXISTS yura_v2")
                c.execute(
                    "CREATE TABLE IF NOT EXISTS yura_v2.persistence_meta "
                    "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )
                row = c.execute(
                    "SELECT value FROM yura_v2.persistence_meta WHERE key = 'memory_schema_version'"
                ).fetchone()
                if row is not None:
                    if row[0] != str(self.storage_schema_version):
                        raise PersistenceError(
                            PersistenceFailureCode.INCOMPATIBLE_STORAGE_VERSION,
                            "記憶保存の構造版に対応していません",
                        )
                    return
                c.execute(
                    "CREATE TABLE yura_v2.memory_records "
                    "(memory_id TEXT PRIMARY KEY, revision BIGINT NOT NULL CHECK(revision >= 0), "
                    "payload TEXT NOT NULL, payload_digest TEXT NOT NULL)"
                )
                c.execute(
                    "CREATE TABLE yura_v2.memory_relations "
                    "(relation_id TEXT PRIMARY KEY, "
                    "left_memory_id TEXT NOT NULL REFERENCES yura_v2.memory_records(memory_id), "
                    "right_memory_id TEXT NOT NULL REFERENCES yura_v2.memory_records(memory_id), "
                    "payload TEXT NOT NULL, payload_digest TEXT NOT NULL)"
                )
                c.execute(
                    "INSERT INTO yura_v2.persistence_meta VALUES ('memory_schema_version', '1')"
                )
        except PersistenceError as error:
            if error.code in {
                PersistenceFailureCode.INCOMPATIBLE_STORAGE_VERSION,
                PersistenceFailureCode.CONNECTION_FAILED,
                PersistenceFailureCode.UNAVAILABLE,
                PersistenceFailureCode.TIMEOUT,
                PersistenceFailureCode.CLOSED,
            }:
                raise
            raise PersistenceError(
                PersistenceFailureCode.MIGRATION_FAILED,
                "PostgreSQLの記憶保存構造を準備できませんでした",
            ) from None

    def get(self, memory_id: str) -> MemoryRecord | None:
        with self._database.transaction() as c:
            row = c.execute(
                "SELECT memory_id, revision, payload, payload_digest "
                "FROM yura_v2.memory_records WHERE memory_id = %s",
                (memory_id,),
            ).fetchone()
            return None if row is None else _decode_record(row)

    def list_records(self) -> tuple[MemoryRecord, ...]:
        return self.snapshot().records

    def list_relations(self) -> tuple[MemoryRelation, ...]:
        return self.snapshot().relations

    def snapshot(self) -> MemoryRepositorySnapshot:
        with self._database.transaction() as c:
            records = c.execute(
                "SELECT memory_id, revision, payload, payload_digest "
                "FROM yura_v2.memory_records ORDER BY memory_id"
            ).fetchall()
            relations = c.execute(
                "SELECT relation_id, left_memory_id, right_memory_id, payload, payload_digest "
                "FROM yura_v2.memory_relations ORDER BY relation_id"
            ).fetchall()
            return MemoryRepositorySnapshot(
                tuple(_decode_record(row) for row in records),
                tuple(_decode_relation(row) for row in relations),
            )

    def _write(self, action: Callable[[PostgresConnection], bool]) -> bool:
        try:
            with self._database.transaction() as c:
                return action(c)
        except PersistenceError as error:
            if error.code in {
                PersistenceFailureCode.PERSISTENCE_CONFLICT,
                PersistenceFailureCode.CONSTRAINT_VIOLATION,
            }:
                # 同一取引の全変更がロールバックされた後に、公開契約の不採用を返す。
                return False
            raise

    def save_record(self, record: MemoryRecord, *, expected_revision: int | None) -> bool:
        if expected_revision is not None:
            require_revision(expected_revision, "expected_revision")

        def write(c: PostgresConnection) -> bool:
            previous = _revision(c, record.memory_id)
            if previous is None:
                if expected_revision is not None or record.revision != 0:
                    return False
                _insert_record(c, record)
            else:
                if previous != expected_revision or record.revision != previous + 1:
                    return False
                _update_record(c, record)
            return True

        return self._write(write)

    def save_relation(self, relation: MemoryRelation) -> bool:
        def write(c: PostgresConnection) -> bool:
            _insert_relation(c, relation)
            return True

        return self._write(write)

    def commit_related(
        self,
        record: MemoryRecord,
        relation: MemoryRelation,
        *,
        target_update: MemoryRecord | None,
        expected_target_revision: int | None,
    ) -> bool:
        if expected_target_revision is not None:
            require_revision(expected_target_revision, "expected_target_revision")

        def write(c: PostgresConnection) -> bool:
            if record.revision != 0:
                return False
            if target_update is None:
                if expected_target_revision is not None:
                    return False
            else:
                previous = _revision(c, target_update.memory_id)
                if (
                    previous is None
                    or previous != expected_target_revision
                    or target_update.revision != previous + 1
                ):
                    return False
            _insert_record(c, record)
            if target_update is not None:
                _update_record(c, target_update)
            # 外部キー違反を含む失敗は、上記の記録・版変更とともに取り消される。
            _insert_relation(c, relation)
            return True

        return self._write(write)


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise PersistenceError(PersistenceFailureCode.CORRUPT_RECORD, "記憶の保存形式が不正です")
    return value


def _revision(c: PostgresConnection, memory_id: str) -> int | None:
    row = c.execute(
        "SELECT revision FROM yura_v2.memory_records WHERE memory_id = %s FOR UPDATE", (memory_id,)
    ).fetchone()
    if row is None:
        return None
    if type(row[0]) is not int:
        raise PersistenceError(PersistenceFailureCode.CORRUPT_RECORD, "記憶の保存版が不正です")
    return row[0]


def _insert_record(c: PostgresConnection, record: MemoryRecord) -> None:
    payload = encode_memory_record(record)
    c.execute(
        "INSERT INTO yura_v2.memory_records VALUES (%s, %s, %s, %s)",
        (record.memory_id, record.revision, payload, _digest(payload)),
    )


def _update_record(c: PostgresConnection, record: MemoryRecord) -> None:
    payload = encode_memory_record(record)
    c.execute(
        "UPDATE yura_v2.memory_records SET revision = %s, payload = %s, payload_digest = %s "
        "WHERE memory_id = %s",
        (record.revision, payload, _digest(payload), record.memory_id),
    )


def _insert_relation(c: PostgresConnection, relation: MemoryRelation) -> None:
    payload = encode_relation(relation)
    c.execute(
        "INSERT INTO yura_v2.memory_relations VALUES (%s, %s, %s, %s, %s)",
        (
            relation.relation_id,
            relation.left_memory_id,
            relation.right_memory_id,
            payload,
            _digest(payload),
        ),
    )


def _digest(payload: str) -> str:
    return sha256(payload.encode("utf-8")).hexdigest()


def _checked_payload(raw: object, digest: object) -> str:
    payload = _text(raw)
    if digest != _digest(payload):
        raise PersistenceError(
            PersistenceFailureCode.INTEGRITY_FAILED, "記憶の保存内容と検査値が一致しません"
        )
    return payload


def _decode_record(row: tuple[object, ...]) -> MemoryRecord:
    record = decode_memory_record(_checked_payload(row[2], row[3]))
    if row[:2] != (record.memory_id, record.revision):
        raise PersistenceError(
            PersistenceFailureCode.INTEGRITY_FAILED, "記憶の保存識別子または版が一致しません"
        )
    return record


def _decode_relation(row: tuple[object, ...]) -> MemoryRelation:
    relation = decode_relation(_checked_payload(row[3], row[4]))
    if row[:3] != (relation.relation_id, relation.left_memory_id, relation.right_memory_id):
        raise PersistenceError(
            PersistenceFailureCode.INTEGRITY_FAILED, "記憶の関係と保存された参照先が一致しません"
        )
    return relation
