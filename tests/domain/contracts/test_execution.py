import json
from datetime import datetime, timedelta, timezone
from typing import cast

import pytest

from app.domain.contracts import (
    AsyncResultStatus,
    AsyncWorkResult,
    ExecutionResult,
    ExecutionStatus,
    JsonInput,
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


def test_execution_result_copies_effect_refs_into_immutable_snapshot() -> None:
    requested = ExecutionResult.requested(
        execution_id="exec-mutable-effect-refs",
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
    mutable_refs = ["effect:1"]
    applied = started.transition_to(
        ExecutionStatus.APPLIED,
        occurred_at=NOW + timedelta(milliseconds=3),
        effect_refs=cast(tuple[str, ...], mutable_refs),
    )

    mutable_refs.append("effect:2")

    assert applied.effect_refs == ("effect:1",)
    assert applied.to_dict()["effect_refs"] == ["effect:1"]


def test_requested_execution_result_rejects_forged_effect_refs() -> None:
    with pytest.raises(ValueError, match="must not contain effect_refs"):
        ExecutionResult(
            execution_id="exec-forged-request",
            command_id="command-effect",
            status=ExecutionStatus.REQUESTED,
            occurred_at=NOW,
            revisions=REVISIONS,
            effect_refs=("effect:forged",),
        )


def test_pre_effect_transition_cannot_introduce_effect_ref() -> None:
    requested = ExecutionResult.requested(
        execution_id="exec-pre-effect",
        command_id="command-effect",
        occurred_at=NOW,
        revisions=REVISIONS,
    )

    with pytest.raises(ValueError, match="cannot be introduced"):
        requested.transition_to(
            ExecutionStatus.ACCEPTED,
            occurred_at=NOW + timedelta(milliseconds=1),
            effect_refs=("effect:too-early",),
        )


def test_effect_refs_cannot_be_erased_by_explicit_empty_successor() -> None:
    requested = ExecutionResult.requested(
        execution_id="exec-preserve-empty",
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
        effect_refs=("effect:1",),
    )
    completed = applied.transition_to(
        ExecutionStatus.COMPLETED,
        occurred_at=NOW + timedelta(milliseconds=4),
        effect_refs=(),
    )

    assert completed.effect_refs == ("effect:1",)


def test_effect_refs_are_additive_on_later_effect_fact() -> None:
    requested = ExecutionResult.requested(
        execution_id="exec-additive-effects",
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
        effect_refs=("effect:1",),
    )
    completed = applied.transition_to(
        ExecutionStatus.COMPLETED,
        occurred_at=NOW + timedelta(milliseconds=4),
        effect_refs=("effect:2",),
    )

    assert completed.effect_refs == ("effect:1", "effect:2")


def test_terminal_failure_cannot_introduce_new_effect_ref() -> None:
    requested = ExecutionResult.requested(
        execution_id="exec-terminal-new-effect",
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
        effect_refs=("effect:1",),
    )

    with pytest.raises(ValueError, match="cannot be introduced"):
        applied.transition_to(
            ExecutionStatus.FAILED,
            occurred_at=NOW + timedelta(milliseconds=4),
            effect_refs=("effect:2",),
        )


def test_started_can_complete_with_direct_effect_fact() -> None:
    requested = ExecutionResult.requested(
        execution_id="exec-direct-complete-effect",
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
    completed = started.transition_to(
        ExecutionStatus.COMPLETED,
        occurred_at=NOW + timedelta(milliseconds=3),
        effect_refs=("effect:direct-complete",),
    )

    assert completed.effect_refs == ("effect:direct-complete",)


def test_execution_result_rejects_non_string_details_key() -> None:
    requested = ExecutionResult.requested(
        execution_id="exec-invalid-details",
        command_id="command-effect",
        occurred_at=NOW,
        revisions=REVISIONS,
    )
    accepted = requested.transition_to(
        ExecutionStatus.ACCEPTED, occurred_at=NOW + timedelta(milliseconds=1)
    )
    details = cast(dict[str, JsonInput], {1: "invalid"})

    with pytest.raises(TypeError, match="JSON object keys must be strings"):
        accepted.transition_to(
            ExecutionStatus.STARTED,
            occurred_at=NOW + timedelta(milliseconds=2),
            details=details,
        )


@pytest.mark.parametrize(
    "status",
    [status for status in ExecutionStatus if status is not ExecutionStatus.REQUESTED],
)
def test_execution_result_rejects_direct_non_requested_construction(
    status: ExecutionStatus,
) -> None:
    with pytest.raises(ValueError, match="require a validated transition"):
        ExecutionResult(
            execution_id="exec-direct",
            command_id="command-direct",
            status=status,
            occurred_at=NOW,
            revisions=REVISIONS,
        )


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


def test_async_result_serializes_optional_started_at() -> None:
    result = AsyncWorkResult(
        request_id="request-timed",
        status=AsyncResultStatus.SUCCEEDED,
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=1),
        revisions=REVISIONS,
        payload={"candidate": "current"},
    )

    serialized = result.to_dict()
    assert serialized["started_at"] == NOW.isoformat()
    assert serialized["completed_at"] == (NOW + timedelta(seconds=1)).isoformat()
    json.dumps(serialized)


def test_async_result_rejects_invalid_started_at() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        AsyncWorkResult(
            request_id="request-naive-start",
            status=AsyncResultStatus.FAILED,
            started_at=datetime(2026, 8, 13),
            completed_at=NOW,
            revisions=REVISIONS,
        )

    with pytest.raises(ValueError, match="must not be later than completed_at"):
        AsyncWorkResult(
            request_id="request-backwards-time",
            status=AsyncResultStatus.FAILED,
            started_at=NOW + timedelta(seconds=2),
            completed_at=NOW + timedelta(seconds=1),
            revisions=REVISIONS,
        )


def test_succeeded_async_result_requires_started_at() -> None:
    with pytest.raises(ValueError, match="succeeded async work requires started_at"):
        AsyncWorkResult(
            request_id="request-success-without-start",
            status=AsyncResultStatus.SUCCEEDED,
            completed_at=NOW,
            revisions=REVISIONS,
        )


@pytest.mark.parametrize(
    "status",
    [status for status in AsyncResultStatus if status is not AsyncResultStatus.SUCCEEDED],
)
def test_non_success_async_result_may_finish_before_work_begins(
    status: AsyncResultStatus,
) -> None:
    result = AsyncWorkResult(
        request_id=f"request-{status.value}-before-start",
        status=status,
        completed_at=NOW,
        revisions=REVISIONS,
    )

    assert result.started_at is None
    assert result.to_dict()["started_at"] is None


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
        started_at=NOW - timedelta(seconds=1),
        completed_at=NOW,
        revisions=REVISIONS,
        payload={"candidate": "current"},
    )

    assert stale.is_committable is False
    assert superseded.is_committable is False
    assert succeeded.is_committable is True
    json.dumps(stale.to_dict())
