"""保存方式に依存しない失敗分類と操作結果の公開契約。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Generic, TypeVar

from app.domain.contracts.common import require_aware, require_identifier, require_revision

T = TypeVar("T")

GOAL_PERSISTENCE_OWNER_ID = "goals"


class PersistenceFailureCode(str, Enum):
    UNAVAILABLE = "unavailable"
    CONNECTION_FAILED = "connection_failed"
    TIMEOUT = "timeout"
    PERSISTENCE_CONFLICT = "persistence_conflict"
    CONSTRAINT_VIOLATION = "constraint_violation"
    INCOMPATIBLE_STORAGE_VERSION = "incompatible_storage_version"
    INCOMPATIBLE_PAYLOAD_VERSION = "incompatible_payload_version"
    MIGRATION_FAILED = "migration_failed"
    CORRUPT_RECORD = "corrupt_record"
    INTEGRITY_FAILED = "integrity_failed"
    CANCELLED = "cancelled"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class PersistenceError(Exception):
    code: PersistenceFailureCode
    diagnostic: str

    def __post_init__(self) -> None:
        if not isinstance(self.code, PersistenceFailureCode):
            raise ValueError("codeが不正です")
        if (
            not isinstance(self.diagnostic, str)
            or not self.diagnostic.strip()
            or len(self.diagnostic) > 256
        ):
            raise ValueError("diagnosticが不正です")


@dataclass(frozen=True, slots=True)
class PersistenceOperationResult(Generic[T]):
    """呼出しの成功値と保存機構の失敗を区別する。生の提供元例外は運ばない。"""

    value: T | None
    failure_code: PersistenceFailureCode | None = None

    def __post_init__(self) -> None:
        if self.failure_code is not None and (
            self.value is not None or not isinstance(self.failure_code, PersistenceFailureCode)
        ):
            raise ValueError("保存処理の成功値と失敗分類が矛盾しています")


class DurabilityStatus(str, Enum):
    DURABLE = "durable"
    PENDING_RETRY = "pending_retry"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SUPERSEDED_BY_NEWER_SNAPSHOT = "superseded_by_newer_snapshot"


@dataclass(frozen=True, slots=True)
class DurabilityReceipt:
    persistence_request_id: str
    owner_id: str
    owner_state_revision: int
    snapshot_or_record_ref: str
    status: DurabilityStatus
    durable_at: datetime | None = None
    storage_revision: int | None = None
    failure_code: PersistenceFailureCode | None = None

    def __post_init__(self) -> None:
        for name in ("persistence_request_id", "owner_id", "snapshot_or_record_ref"):
            require_identifier(getattr(self, name), name)
        require_revision(self.owner_state_revision, "owner_state_revision")
        if not isinstance(self.status, DurabilityStatus):
            raise ValueError("statusが不正です")
        if self.durable_at is not None:
            require_aware(self.durable_at, "durable_at")
        require_revision(self.storage_revision, "storage_revision", optional=True)
        if self.failure_code is not None and not isinstance(
            self.failure_code, PersistenceFailureCode
        ):
            raise ValueError("failure_codeが不正です")
        if self.status is DurabilityStatus.DURABLE and self.durable_at is None:
            raise ValueError("DURABLEにはdurable_atが必要です")
        if self.status is DurabilityStatus.FAILED and self.failure_code is None:
            raise ValueError("FAILEDにはfailure_codeが必要です")
