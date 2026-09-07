"""所有者が復元を許可した状態をPostgreSQLへ保存し、検査済み候補を返す。"""

import json
from collections.abc import Callable
from datetime import datetime, timezone

from app.domain.contracts.common import require_revision

from .contracts import (
    DurabilityReceipt,
    DurabilityStatus,
    IntegrityStatus,
    PersistenceError,
    PersistenceFailureCode,
    PersistenceSnapshotEnvelope,
    RehydrationCandidate,
)
from .postgresql_connection import PostgresDatabase


class PostgresLifecycleSnapshotRepository:
    """保存済みの最大リビジョンを取引で保護する。候補を所有者へ直接適用しない。"""

    storage_version = 1

    def __init__(
        self, database: PostgresDatabase, now: Callable[[], datetime] | None = None
    ) -> None:
        self._database = database
        self._now = now or (lambda: datetime.now(timezone.utc))

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
                    "SELECT value FROM yura_v2.persistence_meta "
                    "WHERE key = 'snapshot_schema_version'"
                ).fetchone()
                if row is not None:
                    if row[0] != str(self.storage_version):
                        raise PersistenceError(
                            PersistenceFailureCode.INCOMPATIBLE_STORAGE_VERSION,
                            "状態保存の構造のバージョンに対応していません",
                        )
                    return
                c.execute(
                    "CREATE TABLE yura_v2.snapshot_heads (owner_id TEXT NOT NULL, "
                    "snapshot_kind TEXT NOT NULL, owner_revision BIGINT NOT NULL "
                    "CHECK(owner_revision >= 0), PRIMARY KEY(owner_id, snapshot_kind))"
                )
                c.execute(
                    "CREATE TABLE yura_v2.lifecycle_snapshots (snapshot_id TEXT PRIMARY KEY, "
                    "owner_id TEXT NOT NULL, snapshot_kind TEXT NOT NULL, "
                    "owner_revision BIGINT NOT NULL CHECK(owner_revision >= 0), "
                    "envelope_json TEXT NOT NULL, obsolete BOOLEAN NOT NULL DEFAULT FALSE, "
                    "rejection_reason TEXT, UNIQUE(owner_id, snapshot_kind, owner_revision), "
                    "FOREIGN KEY(owner_id, snapshot_kind) "
                    "REFERENCES yura_v2.snapshot_heads(owner_id, snapshot_kind))"
                )
                c.execute(
                    "INSERT INTO yura_v2.persistence_meta VALUES ('snapshot_schema_version', '1')"
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
                "PostgreSQLの状態保存構造を準備できませんでした",
            ) from None

    def put_snapshot(
        self, envelope: PersistenceSnapshotEnvelope, *, expected_revision: int | None = None
    ) -> DurabilityReceipt:
        if expected_revision is not None:
            require_revision(expected_revision, "expected_revision")
        with self._database.transaction() as c:
            # 初回作成同士の競合も一意制約と同一取引で拒否する。
            inserted = c.execute(
                "INSERT INTO yura_v2.snapshot_heads VALUES (%s, %s, %s) "
                "ON CONFLICT DO NOTHING RETURNING owner_revision",
                (envelope.owner_id, envelope.snapshot_kind, envelope.owner_state_revision),
            ).fetchone()
            row = c.execute(
                "SELECT owner_revision FROM yura_v2.snapshot_heads "
                "WHERE owner_id = %s AND snapshot_kind = %s FOR UPDATE",
                (envelope.owner_id, envelope.snapshot_kind),
            ).fetchone()
            if row is None or type(row[0]) is not int:
                raise PersistenceError(
                    PersistenceFailureCode.CORRUPT_RECORD, "状態保存の最大リビジョンが不正です"
                )
            latest = row[0]
            if inserted is None:
                if latest > envelope.owner_state_revision:
                    return DurabilityReceipt(
                        envelope.snapshot_id,
                        envelope.owner_id,
                        envelope.owner_state_revision,
                        envelope.snapshot_id,
                        DurabilityStatus.SUPERSEDED_BY_NEWER_SNAPSHOT,
                        storage_revision=latest,
                    )
                if latest == envelope.owner_state_revision or (
                    expected_revision is not None and expected_revision != latest
                ):
                    raise PersistenceError(
                        PersistenceFailureCode.PERSISTENCE_CONFLICT,
                        "状態保存の期待するリビジョンが一致しません",
                    )
            elif expected_revision is not None:
                raise PersistenceError(
                    PersistenceFailureCode.PERSISTENCE_CONFLICT, "期待する保存済み状態がありません"
                )
            c.execute(
                "INSERT INTO yura_v2.lifecycle_snapshots "
                "(snapshot_id, owner_id, snapshot_kind, owner_revision, envelope_json) "
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    envelope.snapshot_id,
                    envelope.owner_id,
                    envelope.snapshot_kind,
                    envelope.owner_state_revision,
                    json.dumps(envelope.to_dict(), ensure_ascii=False, allow_nan=False),
                ),
            )
            c.execute(
                "UPDATE yura_v2.snapshot_heads SET owner_revision = %s "
                "WHERE owner_id = %s AND snapshot_kind = %s",
                (envelope.owner_state_revision, envelope.owner_id, envelope.snapshot_kind),
            )
        # 取引の確定より前には保存完了を返さない。
        return DurabilityReceipt(
            envelope.snapshot_id,
            envelope.owner_id,
            envelope.owner_state_revision,
            envelope.snapshot_id,
            DurabilityStatus.DURABLE,
            self._now(),
            envelope.owner_state_revision,
        )

    def get_latest(self, owner_id: str, snapshot_kind: str) -> RehydrationCandidate | None:
        items = self.list_compatible(owner_id, snapshot_kind, limit=1)
        return items[0] if items else None

    def list_compatible(
        self, owner_id: str, snapshot_kind: str, *, limit: int
    ) -> tuple[RehydrationCandidate, ...]:
        if type(limit) is not int or not 1 <= limit <= 128:
            raise ValueError("取得上限は1から128までの整数で指定してください")
        with self._database.transaction() as c:
            rows = c.execute(
                "SELECT snapshot_id, owner_id, snapshot_kind, owner_revision, envelope_json "
                "FROM yura_v2.lifecycle_snapshots WHERE owner_id = %s AND snapshot_kind = %s "
                "AND NOT obsolete ORDER BY owner_revision DESC LIMIT %s",
                (owner_id, snapshot_kind, limit),
            ).fetchall()
            return tuple(self._decode(row) for row in rows)

    def mark_rejected_or_obsolete(self, snapshot_ref: str, reason: str) -> None:
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 256:
            raise ValueError("不採用理由が不正です")
        with self._database.transaction() as c:
            row = c.execute(
                "UPDATE yura_v2.lifecycle_snapshots SET obsolete = TRUE, rejection_reason = %s "
                "WHERE snapshot_id = %s RETURNING snapshot_id",
                (reason, snapshot_ref),
            ).fetchone()
            if row is None:
                raise PersistenceError(
                    PersistenceFailureCode.CORRUPT_RECORD, "保存状態がありません"
                )
        # 不採用にしても最大リビジョンを戻さず、遅れて到着した古い保存を拒否する。

    def _decode(self, row: tuple[object, ...]) -> RehydrationCandidate:
        try:
            raw = row[4]
            if not isinstance(raw, str):
                raise ValueError
            value = json.loads(raw)
            if not isinstance(value, dict) or set(value) != {
                "snapshot_id",
                "owner_id",
                "snapshot_kind",
                "snapshot_schema_id",
                "snapshot_schema_version",
                "owner_state_revision",
                "runtime_epoch",
                "captured_at",
                "payload",
                "payload_digest",
                "source_refs",
            }:
                raise ValueError
            envelope = PersistenceSnapshotEnvelope(
                value["snapshot_id"],
                value["owner_id"],
                value["snapshot_kind"],
                value["snapshot_schema_id"],
                value["snapshot_schema_version"],
                value["owner_state_revision"],
                value["runtime_epoch"],
                datetime.fromisoformat(value["captured_at"]),
                value["payload"],
                source_refs=value["source_refs"],
            )
            if value["payload_digest"] != envelope.payload_digest or row[:4] != (
                envelope.snapshot_id,
                envelope.owner_id,
                envelope.snapshot_kind,
                envelope.owner_state_revision,
            ):
                raise PersistenceError(
                    PersistenceFailureCode.INTEGRITY_FAILED,
                    "保存状態の内容と識別情報が一致しません",
                )
        except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
            raise PersistenceError(
                PersistenceFailureCode.CORRUPT_RECORD, "保存状態を安全に読み取れません"
            ) from None
        return RehydrationCandidate(
            envelope.snapshot_id,
            envelope.owner_id,
            envelope.snapshot_kind,
            envelope.snapshot_schema_id,
            envelope.snapshot_schema_version,
            envelope.owner_state_revision,
            envelope.runtime_epoch,
            envelope.captured_at,
            envelope.payload,
            IntegrityStatus.VALID,
            self.storage_version,
        )
