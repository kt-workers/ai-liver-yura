"""保存先に依存しない永続化公開契約をまとめて検証する。"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, asdict, replace
from datetime import datetime, timezone
from typing import Any, cast

import pytest

from app.domain.contracts.persistence import (
    GOAL_PERSISTENCE_OWNER_ID,
    DurabilityReceipt,
    DurabilityStatus,
    PersistenceError,
    PersistenceFailureCode,
    PersistenceOperationResult,
)
from app.infrastructure.persistence.contracts import DurabilityReceipt as LegacyReceipt
from app.infrastructure.persistence.contracts import DurabilityStatus as LegacyStatus


def test_failure_classification_preserves_all_wire_values() -> None:
    assert {item.name: item.value for item in PersistenceFailureCode} == {
        "UNAVAILABLE": "unavailable",
        "CONNECTION_FAILED": "connection_failed",
        "TIMEOUT": "timeout",
        "PERSISTENCE_CONFLICT": "persistence_conflict",
        "CONSTRAINT_VIOLATION": "constraint_violation",
        "INCOMPATIBLE_STORAGE_VERSION": "incompatible_storage_version",
        "INCOMPATIBLE_PAYLOAD_VERSION": "incompatible_payload_version",
        "MIGRATION_FAILED": "migration_failed",
        "CORRUPT_RECORD": "corrupt_record",
        "INTEGRITY_FAILED": "integrity_failed",
        "CANCELLED": "cancelled",
        "CLOSED": "closed",
    }
    for item in PersistenceFailureCode:
        assert PersistenceFailureCode(item.value) is item
        failure: PersistenceOperationResult[object] = PersistenceOperationResult(None, item)
        assert failure.value is None and failure.failure_code is item
        error = PersistenceError(item, "既存の失敗事実")
        try:
            raise error
        except PersistenceError as caught:
            assert caught is error
            assert caught.code is item
            assert caught.diagnostic == "既存の失敗事実"


@pytest.mark.parametrize("value", [None, False, 0, "", (), {"memory": "accepted"}])
def test_success_value_is_not_reclassified_by_truthiness(value: object) -> None:
    result = PersistenceOperationResult(value)
    assert result.value is value
    assert result.failure_code is None
    assert asdict(result)["failure_code"] is None


@pytest.mark.parametrize(
    "value,code",
    [(1, PersistenceFailureCode.TIMEOUT), (None, "timeout"), (None, True)],
)
def test_conflicting_or_untyped_failure_is_rejected(value: Any, code: Any) -> None:
    with pytest.raises(ValueError, match="成功値と失敗分類が矛盾"):
        PersistenceOperationResult(value, code)


@pytest.mark.parametrize("diagnostic", ["", "   ", "x" * 257, None])
def test_invalid_failure_diagnostic_is_rejected(diagnostic: Any) -> None:
    with pytest.raises(ValueError, match="diagnostic"):
        PersistenceError(PersistenceFailureCode.UNAVAILABLE, diagnostic)


def test_failure_code_requires_the_canonical_enum() -> None:
    code: Any = "unavailable"
    with pytest.raises(ValueError, match="code"):
        PersistenceError(code, "型を失った失敗")


def test_result_is_an_immutable_dto_with_existing_replace_semantics() -> None:
    result: PersistenceOperationResult[int] = PersistenceOperationResult(5)
    with pytest.raises(FrozenInstanceError):
        result.value = 6  # type: ignore[misc]
    updated = replace(result, value=7)
    assert result.value == 5 and updated.value == 7
    with pytest.raises(ValueError, match="矛盾"):
        replace(result, failure_code=PersistenceFailureCode.CANCELLED)


def test_old_and_new_receipt_paths_share_the_identical_type() -> None:
    assert LegacyReceipt is DurabilityReceipt
    assert LegacyStatus is DurabilityStatus
    assert GOAL_PERSISTENCE_OWNER_ID == "goals"


@pytest.mark.parametrize("status", list(DurabilityStatus))
def test_receipt_preserves_status_and_existing_validation(status: DurabilityStatus) -> None:
    at = datetime(2026, 10, 14, tzinfo=timezone.utc)
    code = PersistenceFailureCode.TIMEOUT if status is DurabilityStatus.FAILED else None
    receipt = DurabilityReceipt("r1", "goals", 1, "s1", status, at, 2, code)
    assert receipt.status is status
    assert receipt.failure_code is code
    assert receipt.durable_at is at
    with pytest.raises(FrozenInstanceError):
        receipt.owner_state_revision = 3  # type: ignore[misc]


@pytest.mark.parametrize("revision", [True, -1, 1.5, "1", None])
def test_invalid_owner_revision_remains_rejected(revision: object) -> None:
    with pytest.raises(ValueError):
        DurabilityReceipt(
            "r1", "goals", cast(int, revision), "s1", DurabilityStatus.PENDING_RETRY
        )


def test_durable_without_time_is_rejected() -> None:
    with pytest.raises(ValueError, match="durable_at"):
        DurabilityReceipt("r1", "goals", 1, "s1", DurabilityStatus.DURABLE)


def test_failed_without_failure_code_is_rejected() -> None:
    with pytest.raises(ValueError, match="failure_code"):
        DurabilityReceipt("r1", "goals", 1, "s1", DurabilityStatus.FAILED)


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError):
        DurabilityReceipt(
            "r1", "goals", 1, "s1", DurabilityStatus.DURABLE, datetime(2026, 10, 14)
        )
