"""永続化の成功事実と失敗分類を、具体的なDB実装から独立して維持する。"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from typing import cast

import pytest

from app.domain.contracts.persistence import (
    GOAL_PERSISTENCE_OWNER_ID,
    DurabilityReceipt,
    DurabilityStatus,
    PersistenceFailureCode,
)
from app.infrastructure.persistence.contracts import DurabilityReceipt as LegacyReceipt
from app.infrastructure.persistence.contracts import DurabilityStatus as LegacyStatus


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
        setattr(receipt, "owner_state_revision", 3)


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
