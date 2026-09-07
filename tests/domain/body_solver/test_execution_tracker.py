from datetime import datetime, timedelta, timezone

import pytest

from app.domain.body_solver import (
    BodyExecutionTransitionError,
    BodyExecutionTransitionFailureCode,
    BodyMotionExecutionReport,
    BodyMotionExecutionStatus,
    BodyMotionExecutionTracker,
    BodyMotionResidual,
)


def test_execution_tracker_requires_physical_start_before_progress() -> None:
    tracker = BodyMotionExecutionTracker("plan-1", "trajectory-1")
    now = datetime(2026, 8, 30, 14, 0, tzinfo=timezone.utc)

    assert tracker.current.status is BodyMotionExecutionStatus.PLANNED
    with pytest.raises(BodyExecutionTransitionError) as error:
        tracker.complete(now)
    assert error.value.code is BodyExecutionTransitionFailureCode.INVALID_TRANSITION


def test_execution_tracker_promotes_started_observable_completed_in_order() -> None:
    tracker = BodyMotionExecutionTracker("plan-1", "trajectory-1")
    started_at = datetime(2026, 8, 30, 14, 0, tzinfo=timezone.utc)
    observable_at = started_at + timedelta(milliseconds=50)
    completed_at = observable_at + timedelta(milliseconds=100)

    assert tracker.start(started_at).status is BodyMotionExecutionStatus.STARTED
    observable = tracker.observe(
        observable_at,
        achieved_target_refs=("goal-1",),
        residuals=(BodyMotionResidual("goal-1", 0.2),),
    )
    assert observable.status is BodyMotionExecutionStatus.OBSERVABLE
    assert observable.observable_at == observable_at

    completed = tracker.complete(
        completed_at,
        achieved_target_refs=("goal-1",),
        residuals=(BodyMotionResidual("goal-1", 0.01),),
    )
    assert completed.status is BodyMotionExecutionStatus.COMPLETED
    assert completed.started_at == started_at
    assert completed.observable_at == observable_at
    assert completed.completed_at == completed_at


def test_execution_tracker_rejects_time_rollback_without_state_change() -> None:
    tracker = BodyMotionExecutionTracker("plan-1", "trajectory-1")
    started_at = datetime(2026, 8, 30, 14, 0, tzinfo=timezone.utc)
    observable_at = started_at + timedelta(milliseconds=50)
    tracker.start(started_at)
    tracker.observe(observable_at)
    before = tracker.current

    with pytest.raises(BodyExecutionTransitionError) as error:
        tracker.observe(started_at)

    assert error.value.code is BodyExecutionTransitionFailureCode.TIME_ROLLBACK
    assert tracker.current == before


def test_execution_tracker_rejects_duplicate_start_and_post_completion_progress() -> None:
    tracker = BodyMotionExecutionTracker("plan-1", "trajectory-1")
    started_at = datetime(2026, 8, 30, 14, 0, tzinfo=timezone.utc)
    tracker.start(started_at)

    with pytest.raises(BodyExecutionTransitionError):
        tracker.start(started_at)

    tracker.complete(started_at + timedelta(milliseconds=100))
    with pytest.raises(BodyExecutionTransitionError):
        tracker.observe(started_at + timedelta(milliseconds=101))


def test_execution_tracker_does_not_report_unstarted_plan_as_interrupted_or_superseded() -> None:
    now = datetime(2026, 8, 30, 14, 0, tzinfo=timezone.utc)
    interrupted = BodyMotionExecutionTracker("plan-1", "trajectory-1")
    superseded = BodyMotionExecutionTracker("plan-2", "trajectory-2")

    with pytest.raises(BodyExecutionTransitionError) as interrupt_error:
        interrupted.interrupt(now)
    with pytest.raises(BodyExecutionTransitionError) as supersede_error:
        superseded.supersede(now)

    assert interrupt_error.value.code is BodyExecutionTransitionFailureCode.INVALID_TRANSITION
    assert supersede_error.value.code is BodyExecutionTransitionFailureCode.INVALID_TRANSITION
    assert interrupted.current.status is BodyMotionExecutionStatus.PLANNED
    assert superseded.current.status is BodyMotionExecutionStatus.PLANNED


def test_execution_tracker_supersede_preserves_terminal_time_and_last_evidence() -> None:
    tracker = BodyMotionExecutionTracker("plan-1", "trajectory-1")
    started_at = datetime(2026, 8, 30, 14, 0, tzinfo=timezone.utc)
    observable_at = started_at + timedelta(milliseconds=16)
    superseded_at = observable_at + timedelta(milliseconds=16)
    evidence = (BodyMotionResidual("goal-1", 0.25),)

    tracker.start(started_at)
    tracker.observe(
        observable_at,
        achieved_target_refs=("goal-1",),
        residuals=evidence,
    )
    report = tracker.supersede(
        superseded_at,
        achieved_target_refs=("goal-1",),
        residuals=evidence,
    )

    assert report.status is BodyMotionExecutionStatus.SUPERSEDED
    assert report.started_at == started_at
    assert report.observable_at == observable_at
    assert report.completed_at == superseded_at
    assert report.achieved_target_refs == ("goal-1",)
    assert report.residuals == evidence
    with pytest.raises(BodyExecutionTransitionError):
        tracker.complete(superseded_at + timedelta(milliseconds=1))


def test_execution_tracker_interrupt_is_terminal_and_keeps_last_evidence() -> None:
    tracker = BodyMotionExecutionTracker("plan-1", "trajectory-1")
    started_at = datetime(2026, 8, 30, 14, 0, tzinfo=timezone.utc)
    interrupted_at = started_at + timedelta(milliseconds=16)
    evidence = (BodyMotionResidual("goal-1", 0.5),)

    tracker.start(started_at)
    report = tracker.interrupt(
        interrupted_at,
        achieved_target_refs=(),
        residuals=evidence,
    )

    assert report.status is BodyMotionExecutionStatus.INTERRUPTED
    assert report.completed_at == interrupted_at
    assert report.residuals == evidence
    with pytest.raises(BodyExecutionTransitionError):
        tracker.observe(interrupted_at + timedelta(milliseconds=1))


def test_terminal_actual_report_requires_terminal_timestamp() -> None:
    started_at = datetime(2026, 8, 30, 14, 0, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="completed_at"):
        BodyMotionExecutionReport(
            "plan-1",
            "trajectory-1",
            BodyMotionExecutionStatus.SUPERSEDED,
            started_at=started_at,
        )
