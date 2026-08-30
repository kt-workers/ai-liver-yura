from datetime import datetime, timedelta, timezone

import pytest

from app.domain.body_integration import (
    BodyExecutionSession,
    BodyExecutionSessionStatus,
    BodyIntegrationTrace,
)

NOW = datetime(2026, 8, 30, tzinfo=timezone.utc)


def _trace(*, motion_plan_id: str | None = None) -> BodyIntegrationTrace:
    return BodyIntegrationTrace(
        "trace:body:1",
        "decision:1",
        "intent:1",
        "command:1",
        motion_plan_id,
        "body.v1",
        3,
        4,
        5,
        6,
        7,
        NOW,
    )


def test_trace_keeps_the_committed_body_lineage_and_start_revisions() -> None:
    trace = _trace(motion_plan_id="plan:1")

    assert trace.decision_id == "decision:1"
    assert trace.motion_plan_id == "plan:1"
    assert trace.body_state_revision_start == 6


def test_realtime_only_trace_does_not_invent_a_motion_plan() -> None:
    trace = _trace()

    assert trace.motion_plan_id is None


def test_session_is_a_read_model_that_requires_a_plan_only_when_it_uses_one() -> None:
    admitted = BodyExecutionSession(
        "session:1",
        _trace(),
        BodyExecutionSessionStatus.ADMITTED,
        None,
        6,
    )
    executing = BodyExecutionSession(
        "session:2",
        _trace(motion_plan_id="plan:1"),
        BodyExecutionSessionStatus.EXECUTING,
        "plan:1",
        8,
        NOW,
    )

    assert admitted.current_body_state_revision == 6
    assert executing.active_plan_id == "plan:1"


def test_session_rejects_state_regression_and_incomplete_terminal_state() -> None:
    with pytest.raises(ValueError, match="開始時"):
        BodyExecutionSession(
            "session:1",
            _trace(),
            BodyExecutionSessionStatus.PLANNING,
            None,
            5,
            NOW,
        )

    with pytest.raises(ValueError, match="完了時刻"):
        BodyExecutionSession(
            "session:1",
            _trace(),
            BodyExecutionSessionStatus.CANCELLED,
            None,
            6,
            NOW,
        )


def test_session_rejects_plan_dependent_state_without_a_plan() -> None:
    with pytest.raises(ValueError, match="active_plan_id"):
        BodyExecutionSession(
            "session:1",
            _trace(),
            BodyExecutionSessionStatus.EXECUTING,
            None,
            6,
            NOW,
        )


def test_terminal_session_keeps_completed_effect_history_without_time_reversal() -> None:
    completed = BodyExecutionSession(
        "session:1",
        _trace(motion_plan_id="plan:1"),
        BodyExecutionSessionStatus.COMPLETED,
        "plan:1",
        9,
        NOW,
        NOW + timedelta(seconds=2),
        "trajectory_completed",
    )

    assert completed.completed_at == NOW + timedelta(seconds=2)
