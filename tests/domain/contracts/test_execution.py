import json
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.contracts import (
    AsyncResultStatus,
    AsyncWorkResult,
    ExecutionResult,
    ExecutionStatus,
    RevisionVector,
    validate_execution_transition,
)

NOW = datetime(2026, 8, 13, 0, 0, tzinfo=timezone.utc)
REVISIONS = RevisionVector(source_context_revision=5, goal_revision=3)


def test_execution_result_follows_truth_lifecycle() -> None:
    requested = ExecutionResult.requested(
        execution_id="exec-1",
        command_id="command-1",
        occurred_at=NOW,
        revisions=REVISIONS,
    )
    accepted = requested.transition_to(
        ExecutionStatus.ACCEPTED, occurred_at=NOW + timedelta(milliseconds=1)
    )
    started = accepted.transition_to(
        ExecutionStatus.STARTED, occurred_at=NOW + timedelta(milliseconds=2)
    )
    observable = started.transition_to(
        ExecutionStatus.OBSERVABLE,
        occurred_at=NOW + timedelta(milliseconds=3),
        effect_refs=("body-frame:100",),
    )
    completed = observable.transition_to(
        ExecutionStatus.COMPLETED,
        occurred_at=NOW + timedelta(milliseconds=4),
        details={"applied": True},
        effect_refs=("body-frame:100",),
    )

    assert completed.status is ExecutionStatus.COMPLETED
    assert completed.status.is_terminal is True
    assert completed.to_dict()["effect_refs"] == ["body-frame:100"]
    json.dumps(completed.to_dict())


def test_execution_result_supports_applied_effect_milestone() -> None:
    requested = ExecutionResult.requested(
        execution_id="exec-effect",
        command_id="command-effect",
        occurred_at=NOW,
        revisions=REVISIONS,
    )
    accepted = requested.transition_to(
        ExecutionStatus.ACCEPTED, occurred_at=NOW + timedelta(milliseconds=1)
    )
    started = accepted.transition_to(
        ExecutionStatus.STARTED, occurred_at=NOW + timedelta(milliseconds=2)
    )
    applied = started.transition_to(
        ExecutionStatus.APPLIED,
        occurred_at=NOW + timedelta(milliseconds=3),
        details={"external_effect_applied": True},
        effect_refs=("effect:1",),
    )
    completed = applied.transition_to(
        ExecutionStatus.COMPLETED, occurred_at=NOW + timedelta(milliseconds=4)
    )

    assert applied.status is ExecutionStatus.APPLIED
    assert applied.status.is_terminal is False
    assert completed.status is ExecutionStatus.COMPLETED
    assert completed.to_dict()["details"] == {"external_effect_applied": True}
    assert completed.effect_refs == ("effect:1",)


def test_execution_result_preserves_actual_fact_when_later_transition_fails() -> None:
    requested = ExecutionResult.requested(
        execution_id="exec-failed-after-effect",
        command_id="command-effect",
        occurred_at=NOW,
        revisions=REVISIONS,
    )
    accepted = requested.transition_to(
        ExecutionStatus.ACCEPTED, occurred_at=NOW + timedelta(milliseconds=1)
    )
    started = accepted.transition_to(
        ExecutionStatus.STARTED, occurred_at=NOW + timedelta(milliseconds=2)
    )
    applied = started.transition_to(
        ExecutionStatus.APPLIED,
        occurred_at=NOW + timedelta(milliseconds=3),
        details={"external_effect_applied": True},
        effect_refs=("effect:1",),
    )
    failed = applied.transition_to(
        ExecutionStatus.FAILED,
        occurred_at=NOW + timedelta(milliseconds=4),
        reason_code="post_effect_confirmation_failed",
    )

    assert failed.status is ExecutionStatus.FAILED
    assert failed.to_dict()["details"] == {"external_effect_applied": True}
    assert failed.effect_refs == ("effect:1",)


def test_execution_transition_rejects_intent_to_completed_shortcut() -> None:
    with pytest.raises(ValueError, match="requested -> completed"):
        validate_execution_transition(ExecutionStatus.REQUESTED, ExecutionStatus.COMPLETED)


def test_execution_transition_rejects_backwards_timestamp() -> None:
    requested = ExecutionResult.requested(
        execution_id="exec-time",
        command_id="command-time",
        occurred_at=NOW,
        revisions=REVISIONS,
    )
    accepted = requested.transition_to(
        ExecutionStatus.ACCEPTED, occurred_at=NOW + timedelta(milliseconds=2)
    )

    with pytest.raises(ValueError, match="must not move backwards"):
        accepted.transition_to(
            ExecutionStatus.STARTED,
            occurred_at=NOW + timedelta(milliseconds=1),
        )


def test_terminal_execution_result_cannot_transition_again() -> None:
    requested = ExecutionResult.requested(
        execution_id="exec-1",
        command_id="command-1",
        occurred_at=NOW,
        revisions=REVISIONS,
    )
    rejected = requested.transition_to(
        ExecutionStatus.REJECTED, occurred_at=NOW + timedelta(seconds=1)
    )

    with pytest.raises(ValueError, match="rejected -> accepted"):
        rejected.transition_to(ExecutionStatus.ACCEPTED, occurred_at=NOW + timedelta(seconds=2))


def test_stale_and_superseded_async_results_are_not_committable() -> None:
    stale = AsyncWorkResult(
        request_id="request-1",
        status=AsyncResultStatus.STALE,
        completed_at=NOW,
        revisions=REVISIONS,
        payload={"candidate": "old"},
        reason_code="source_context_revision_changed",
    )
    superseded = AsyncWorkResult(
        request_id="request-2",
        status=AsyncResultStatus.SUPERSEDED,
        completed_at=NOW,
        revisions=REVISIONS,
    )
    succeeded = AsyncWorkResult(
        request_id="request-3",
        status=AsyncResultStatus.SUCCEEDED,
        completed_at=NOW,
        revisions=REVISIONS,
        payload={"candidate": "current"},
    )

    assert stale.is_committable is False
    assert superseded.is_committable is False
    assert succeeded.is_committable is True
    json.dumps(stale.to_dict())
