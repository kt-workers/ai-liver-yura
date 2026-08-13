from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.domain.contracts import (
    AsyncWorkResult,
    AsyncWorkStatus,
    ExecutionResult,
    ExecutionStatus,
    RevisionVector,
)

NOW = datetime(2026, 8, 14, 0, 0, tzinfo=timezone.utc)
REVISIONS = RevisionVector(5, goal_revision=6, attention_revision=7)


def requested(*, details: object = None) -> ExecutionResult:
    return ExecutionResult(
        "command-1",
        ExecutionStatus.REQUESTED,
        NOW,
        REVISIONS,
        {} if details is None else details,  # type: ignore[arg-type]
    )


def started() -> ExecutionResult:
    return requested().transition_to(ExecutionStatus.ACCEPTED, NOW).transition_to(
        ExecutionStatus.STARTED, NOW + timedelta(seconds=1)
    )


@pytest.mark.parametrize(
    "status", [item for item in ExecutionStatus if item is not ExecutionStatus.REQUESTED]
)
def test_direct_non_requested_construction_is_rejected(status: ExecutionStatus) -> None:
    with pytest.raises(ValueError, match="validated transition"):
        ExecutionResult("command-1", status, NOW, REVISIONS)


def test_requested_cannot_claim_effect() -> None:
    with pytest.raises(ValueError, match="cannot contain effect_refs"):
        ExecutionResult(
            "command-1", ExecutionStatus.REQUESTED, NOW, REVISIONS, {}, ("effect-1",)
        )


def test_valid_lifecycle_preserves_details_and_effects() -> None:
    first = requested(details={"request": "accepted"})
    observable = (
        first.transition_to(ExecutionStatus.ACCEPTED, NOW)
        .transition_to(ExecutionStatus.STARTED, NOW + timedelta(seconds=1))
        .transition_to(
            ExecutionStatus.OBSERVABLE,
            NOW + timedelta(seconds=2),
            effect_refs=["speech-audible"],
        )
    )
    completed = observable.transition_to(
        ExecutionStatus.COMPLETED,
        NOW + timedelta(seconds=3),
        effect_refs=(),
    )

    assert completed.details == first.details
    assert completed.effect_refs == ("speech-audible",)
    assert completed.to_dict()["effect_refs"] == ["speech-audible"]


def test_completed_may_record_first_effect_after_started() -> None:
    completed = started().transition_to(
        ExecutionStatus.COMPLETED,
        NOW + timedelta(seconds=2),
        effect_refs=("database-write",),
    )
    assert completed.effect_refs == ("database-write",)


def test_effects_are_additive_and_ordered() -> None:
    observable = started().transition_to(
        ExecutionStatus.OBSERVABLE,
        NOW + timedelta(seconds=2),
        effect_refs=("effect-1",),
    )
    completed = observable.transition_to(
        ExecutionStatus.COMPLETED,
        NOW + timedelta(seconds=3),
        effect_refs=("effect-1", "effect-2"),
    )
    assert completed.effect_refs == ("effect-1", "effect-2")


@pytest.mark.parametrize(
    "status",
    [
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.TIMED_OUT,
        ExecutionStatus.SUPERSEDED,
    ],
)
def test_terminal_outcome_preserves_but_cannot_introduce_effect(status: ExecutionStatus) -> None:
    observable = started().transition_to(
        ExecutionStatus.OBSERVABLE,
        NOW + timedelta(seconds=2),
        effect_refs=("effect-1",),
    )
    terminal = observable.transition_to(status, NOW + timedelta(seconds=3))
    assert terminal.effect_refs == ("effect-1",)
    with pytest.raises(ValueError, match="cannot introduce"):
        observable.transition_to(
            status,
            NOW + timedelta(seconds=3),
            effect_refs=("effect-2",),
        )


def test_non_effect_status_cannot_introduce_effect() -> None:
    with pytest.raises(ValueError, match="cannot introduce"):
        requested().transition_to(
            ExecutionStatus.ACCEPTED, NOW, effect_refs=("invented",)
        )


def test_invalid_lifecycle_edge_is_rejected() -> None:
    with pytest.raises(ValueError, match="invalid execution transition"):
        requested().transition_to(ExecutionStatus.COMPLETED, NOW)


def test_transition_rejects_backwards_absolute_time() -> None:
    with pytest.raises(ValueError, match="backwards"):
        requested().transition_to(ExecutionStatus.ACCEPTED, NOW - timedelta(microseconds=1))


def test_transition_orders_dst_fold_by_absolute_instant() -> None:
    zone = ZoneInfo("America/New_York")
    first = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0)
    second = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=1)
    result = ExecutionResult("command-1", ExecutionStatus.REQUESTED, first, REVISIONS)
    assert result.transition_to(ExecutionStatus.ACCEPTED, second).occurred_at is second


def test_details_are_replaced_only_when_explicitly_supplied() -> None:
    accepted = requested(details={"stage": "request"}).transition_to(
        ExecutionStatus.ACCEPTED, NOW, details={"stage": "accepted"}
    )
    assert accepted.to_dict()["details"] == {"stage": "accepted"}


def async_result(
    status: AsyncWorkStatus,
    *,
    started_at: datetime | None = NOW,
    completed_at: datetime = NOW + timedelta(seconds=1),
) -> AsyncWorkResult:
    return AsyncWorkResult(
        "request-1", status, REVISIONS, completed_at, {"candidate": "value"}, started_at
    )


def test_only_succeeded_async_result_is_inherently_committable() -> None:
    assert async_result(AsyncWorkStatus.SUCCEEDED).is_committable
    for status in AsyncWorkStatus:
        if status is not AsyncWorkStatus.SUCCEEDED:
            assert not async_result(status, started_at=None).is_committable


def test_successful_async_work_requires_start() -> None:
    with pytest.raises(ValueError, match="requires started_at"):
        async_result(AsyncWorkStatus.SUCCEEDED, started_at=None)


@pytest.mark.parametrize(
    "status",
    [
        AsyncWorkStatus.FAILED,
        AsyncWorkStatus.CANCELLED,
        AsyncWorkStatus.TIMED_OUT,
        AsyncWorkStatus.STALE,
        AsyncWorkStatus.SUPERSEDED,
        AsyncWorkStatus.REJECTED,
    ],
)
def test_non_success_async_work_may_end_before_start(status: AsyncWorkStatus) -> None:
    assert async_result(status, started_at=None).started_at is None


def test_async_result_rejects_start_after_completion() -> None:
    with pytest.raises(ValueError, match="later"):
        async_result(
            AsyncWorkStatus.FAILED,
            started_at=NOW + timedelta(seconds=2),
            completed_at=NOW + timedelta(seconds=1),
        )


def test_async_result_orders_dst_fold_by_absolute_instant() -> None:
    zone = ZoneInfo("America/New_York")
    started_at = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0)
    completed_at = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=1)
    result = async_result(
        AsyncWorkStatus.SUCCEEDED, started_at=started_at, completed_at=completed_at
    )
    assert result.completed_at is completed_at


def test_async_result_serializes_both_timestamps_and_owned_result() -> None:
    payload = ["candidate"]
    result = AsyncWorkResult(
        "request-1",
        AsyncWorkStatus.SUCCEEDED,
        REVISIONS,
        NOW + timedelta(seconds=1),
        {"items": payload},  # type: ignore[dict-item]
        NOW,
    )
    payload.append("mutated")
    assert result.to_dict() == {
        "request_id": "request-1",
        "status": "succeeded",
        "revisions": REVISIONS.to_dict(),
        "started_at": NOW.isoformat(),
        "completed_at": (NOW + timedelta(seconds=1)).isoformat(),
        "result": {"items": ["candidate"]},
        "error_code": None,
    }
