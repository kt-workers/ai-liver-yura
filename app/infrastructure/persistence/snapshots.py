"""#359のrestart-safe snapshot storage surface。"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone
from threading import RLock
from typing import Protocol

from .contracts import (
    DurabilityReceipt,
    DurabilityStatus,
    IntegrityStatus,
    PersistenceAvailability,
    PersistenceError,
    PersistenceFailureCode,
    PersistenceSnapshotEnvelope,
    RehydrationCandidate,
)


class LifecycleSnapshotRepositoryPort(Protocol):
    def put_snapshot(
        self,
        envelope: PersistenceSnapshotEnvelope,
        *,
        expected_revision: int | None = None,
    ) -> DurabilityReceipt: ...

    def get_latest(self, owner_id: str, snapshot_kind: str) -> RehydrationCandidate | None: ...

    def list_compatible(
        self,
        owner_id: str,
        snapshot_kind: str,
        *,
        limit: int,
    ) -> tuple[RehydrationCandidate, ...]: ...

    def mark_rejected_or_obsolete(self, snapshot_ref: str, reason: str) -> None: ...


class InMemoryLifecycleSnapshotRepository:
    """安全なserialized envelopeだけを保つ単体検証用storage adapter。"""

    storage_version = 1

    def __init__(self, now: Callable[[], datetime] | None = None) -> None:
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._records: dict[str, PersistenceSnapshotEnvelope] = {}
        self._obsolete: set[str] = set()
        self.availability = PersistenceAvailability.AVAILABLE

    def put_snapshot(
        self,
        envelope: PersistenceSnapshotEnvelope,
        *,
        expected_revision: int | None = None,
    ) -> DurabilityReceipt:
        self._ensure_available()
        latest = self._latest_envelope(envelope.owner_id, envelope.snapshot_kind)
        if latest is not None:
            if latest.owner_state_revision > envelope.owner_state_revision:
                return DurabilityReceipt(
                    envelope.snapshot_id,
                    envelope.owner_id,
                    envelope.owner_state_revision,
                    envelope.snapshot_id,
                    DurabilityStatus.SUPERSEDED_BY_NEWER_SNAPSHOT,
                    storage_revision=latest.owner_state_revision,
                )
            if expected_revision is not None and expected_revision != latest.owner_state_revision:
                raise PersistenceError(
                    PersistenceFailureCode.PERSISTENCE_CONFLICT,
                    "revision不一致",
                )
            if (
                expected_revision is None
                and latest.owner_state_revision == envelope.owner_state_revision
            ):
                raise PersistenceError(
                    PersistenceFailureCode.PERSISTENCE_CONFLICT,
                    "revision不一致",
                )
        elif expected_revision is not None:
            raise PersistenceError(
                PersistenceFailureCode.PERSISTENCE_CONFLICT,
                "対象snapshotがありません",
            )
        if envelope.snapshot_id in self._records:
            raise PersistenceError(
                PersistenceFailureCode.CONSTRAINT_VIOLATION,
                "snapshot_idが重複しています",
            )
        self._records[envelope.snapshot_id] = envelope
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
        self._ensure_available()
        envelope = self._latest_envelope(owner_id, snapshot_kind)
        return None if envelope is None else self._candidate(envelope)

    def list_compatible(
        self,
        owner_id: str,
        snapshot_kind: str,
        *,
        limit: int,
    ) -> tuple[RehydrationCandidate, ...]:
        self._ensure_available()
        if type(limit) is not int or not 1 <= limit <= 128:
            raise ValueError("limitが不正です")
        records = sorted(
            (
                item
                for item in self._records.values()
                if item.owner_id == owner_id
                and item.snapshot_kind == snapshot_kind
                and item.snapshot_id not in self._obsolete
            ),
            key=lambda item: (item.owner_state_revision, item.captured_at, item.snapshot_id),
            reverse=True,
        )
        return tuple(self._candidate(item) for item in records[:limit])

    def mark_rejected_or_obsolete(self, snapshot_ref: str, reason: str) -> None:
        self._ensure_available()
        if snapshot_ref not in self._records:
            raise PersistenceError(PersistenceFailureCode.CORRUPT_RECORD, "snapshotがありません")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 256:
            raise ValueError("reasonが不正です")
        self._obsolete.add(snapshot_ref)

    def close(self) -> None:
        self.availability = PersistenceAvailability.CLOSED

    def _latest_envelope(
        self, owner_id: str, snapshot_kind: str
    ) -> PersistenceSnapshotEnvelope | None:
        records = [
            item
            for item in self._records.values()
            if item.owner_id == owner_id
            and item.snapshot_kind == snapshot_kind
            and item.snapshot_id not in self._obsolete
        ]
        return max(
            records,
            default=None,
            key=lambda item: (item.owner_state_revision, item.captured_at, item.snapshot_id),
        )

    def _candidate(self, envelope: PersistenceSnapshotEnvelope) -> RehydrationCandidate:
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

    def _ensure_available(self) -> None:
        if self.availability is PersistenceAvailability.CLOSED:
            raise PersistenceError(PersistenceFailureCode.CLOSED, "persistenceはclose済みです")
        if self.availability is not PersistenceAvailability.AVAILABLE:
            raise PersistenceError(
                PersistenceFailureCode.UNAVAILABLE,
                "persistenceを利用できません",
            )


class SqliteLifecycleSnapshotRepository(InMemoryLifecycleSnapshotRepository):
    """safe JSON envelopeをSQLiteへ永続化する#359 adapter。"""

    storage_schema_version = 1

    def __init__(self, database_path: str, now: Callable[[], datetime] | None = None) -> None:
        super().__init__(now)
        self._lock = RLock()
        self._corrupt_snapshot_refs: set[str] = set()
        try:
            self._connection = sqlite3.connect(database_path, check_same_thread=False)
            self._migrate()
            self._load()
        except PersistenceError:
            raise
        except sqlite3.Error as error:
            raise PersistenceError(
                PersistenceFailureCode.CONNECTION_FAILED,
                "storage接続に失敗しました",
            ) from error

    @property
    def corrupt_snapshot_refs(self) -> tuple[str, ...]:
        """起動時に隔離した破損recordを、payloadを出さずに診断可能にする。"""
        return tuple(sorted(self._corrupt_snapshot_refs))

    def put_snapshot(
        self,
        envelope: PersistenceSnapshotEnvelope,
        *,
        expected_revision: int | None = None,
    ) -> DurabilityReceipt:
        try:
            with self._lock:
                receipt = super().put_snapshot(envelope, expected_revision=expected_revision)
                if receipt.status is not DurabilityStatus.DURABLE:
                    return receipt
                self._connection.execute(
                    "INSERT INTO lifecycle_snapshots VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        envelope.snapshot_id,
                        envelope.owner_id,
                        envelope.snapshot_kind,
                        envelope.owner_state_revision,
                        envelope.captured_at.isoformat(),
                        json.dumps(
                            envelope.to_dict(),
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                            allow_nan=False,
                        ),
                        0,
                    ),
                )
                self._connection.commit()
        except sqlite3.Error as error:
            self._records.pop(envelope.snapshot_id, None)
            raise PersistenceError(
                PersistenceFailureCode.UNAVAILABLE,
                "snapshotの永続化に失敗しました",
            ) from error
        return receipt

    def get_latest(self, owner_id: str, snapshot_kind: str) -> RehydrationCandidate | None:
        with self._lock:
            return super().get_latest(owner_id, snapshot_kind)

    def list_compatible(
        self, owner_id: str, snapshot_kind: str, *, limit: int
    ) -> tuple[RehydrationCandidate, ...]:
        with self._lock:
            return super().list_compatible(owner_id, snapshot_kind, limit=limit)

    def mark_rejected_or_obsolete(self, snapshot_ref: str, reason: str) -> None:
        try:
            with self._lock:
                if snapshot_ref not in self._records:
                    raise PersistenceError(
                        PersistenceFailureCode.CORRUPT_RECORD, "snapshotがありません"
                    )
                if not isinstance(reason, str) or not reason.strip() or len(reason) > 256:
                    raise ValueError("reasonが不正です")
                self._connection.execute(
                    "UPDATE lifecycle_snapshots SET obsolete = 1 WHERE snapshot_id = ?",
                    (snapshot_ref,),
                )
                self._connection.commit()
                self._obsolete.add(snapshot_ref)
        except sqlite3.Error as error:
            raise PersistenceError(
                PersistenceFailureCode.UNAVAILABLE,
                "snapshot状態の更新に失敗しました",
            ) from error

    def close(self) -> None:
        if self.availability is PersistenceAvailability.CLOSED:
            return
        with self._lock:
            self._connection.close()
        super().close()

    def _migrate(self) -> None:
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS persistence_meta "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS lifecycle_snapshots "
            "(snapshot_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, "
            "snapshot_kind TEXT NOT NULL, owner_revision INTEGER NOT NULL, "
            "captured_at TEXT NOT NULL, envelope_json TEXT NOT NULL, obsolete INTEGER NOT NULL)"
        )
        row = self._connection.execute(
            "SELECT value FROM persistence_meta WHERE key = 'schema_version'"
        ).fetchone()
        if row is not None:
            try:
                stored_version = int(row[0])
            except (TypeError, ValueError) as error:
                raise PersistenceError(
                    PersistenceFailureCode.MIGRATION_FAILED,
                    "storage schema versionが不正です",
                ) from error
            if stored_version < 0:
                raise PersistenceError(
                    PersistenceFailureCode.MIGRATION_FAILED,
                    "storage schema versionが不正です",
                )
            if stored_version > self.storage_schema_version:
                raise PersistenceError(
                    PersistenceFailureCode.INCOMPATIBLE_STORAGE_VERSION,
                    "storage schemaが新しすぎます",
                )
        self._connection.execute(
            "INSERT OR REPLACE INTO persistence_meta VALUES ('schema_version', ?)",
            (str(self.storage_schema_version),),
        )
        self._connection.commit()

    def _load(self) -> None:
        rows = self._connection.execute(
            "SELECT snapshot_id, envelope_json, obsolete FROM lifecycle_snapshots"
        ).fetchall()
        for snapshot_ref, raw, obsolete in rows:
            try:
                envelope = self._decode_envelope(raw)
            except PersistenceError:
                self._corrupt_snapshot_refs.add(str(snapshot_ref))
                continue
            self._records[envelope.snapshot_id] = envelope
            if obsolete:
                self._obsolete.add(envelope.snapshot_id)

    @staticmethod
    def _decode_envelope(raw: object) -> PersistenceSnapshotEnvelope:
        try:
            if not isinstance(raw, str):
                raise ValueError
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError
            return PersistenceSnapshotEnvelope(
                value["snapshot_id"],
                value["owner_id"],
                value["snapshot_kind"],
                value["snapshot_schema_id"],
                value["snapshot_schema_version"],
                value["owner_state_revision"],
                value["runtime_epoch"],
                datetime.fromisoformat(value["captured_at"]),
                value["payload"],
                value["payload_digest"],
                tuple(value["source_refs"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise PersistenceError(
                PersistenceFailureCode.CORRUPT_RECORD,
                "snapshot recordが不正です",
            ) from error
