from datetime import datetime, timedelta, timezone

from app.domain.drives import DriveState
from app.runtime.activity_manager import ActivityManager
from app.runtime.agent_state import AgentState
from app.runtime.autonomous_activity_policy import AutonomousActivityPolicy
from app.runtime.autonomous_event_planner import AutonomousEventPlanner
from app.runtime.autonomous_plan_state import AutonomousPlanState
from app.runtime.conversation_resume_state import ConversationResumeState


def build_planner(
    *,
    activity_manager: ActivityManager | None = None,
    plan_state: AutonomousPlanState | None = None,
    pending_confirmation: bool = False,
    idle_timeout_seconds: float = 30.0,
) -> AutonomousEventPlanner:
    return AutonomousEventPlanner(
        activity_manager or ActivityManager(),
        autonomous_activity_policy=AutonomousActivityPolicy(),
        autonomous_plan_state=plan_state or AutonomousPlanState(),
        conversation_resume_state=ConversationResumeState(),
        pending_confirmation_provider=lambda: pending_confirmation,
        conversation_idle_timeout_seconds=idle_timeout_seconds,
    )


def plan(planner: AutonomousEventPlanner, state: AgentState, now: datetime):
    return planner.plan(
        state,
        now=now,
        awakening_completed_at=None,
        continuation_provider=lambda: None,
        autonomous_topic_provider=lambda: None,
    )


def test_pending_confirmation_skips_autonomous_event() -> None:
    now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)

    result = plan(
        build_planner(pending_confirmation=True),
        AgentState(current_drive=DriveState(curiosity=0.9, energy=0.9)),
        now,
    )

    assert result.event is None
    assert result.skip_reason == "pending_confirmation_exists"
    assert result.log_level == "debug"


def test_recent_user_input_waits_for_idle_timeout() -> None:
    now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    state = AgentState(
        current_drive=DriveState(curiosity=0.9, energy=0.9),
        last_user_input_at=now - timedelta(seconds=10),
    )

    result = plan(build_planner(idle_timeout_seconds=30.0), state, now)

    assert result.event is None
    assert result.skip_reason == "conversation_idle_timeout_not_reached"


def test_strong_drive_creates_curiosity_peak_event() -> None:
    now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    state = AgentState(current_drive=DriveState(curiosity=0.9, energy=0.9))

    result = plan(build_planner(), state, now)

    assert result.planned is True
    assert result.event is not None
    assert result.event.payload["reason"] == "internal_drive"
    assert result.event.payload["drive"] == "curiosity"
    assert result.event.payload["autonomous_planned_for"] == now.isoformat()
    assert "resume_reason" not in result.event.payload
    assert result.event.discardable is True
    assert result.event.replace_key == "agent_life_service:curiosity_peak"
    assert result.log_event == "agent_life_service:plan_next_event:planned"


def test_retry_backoff_skips_autonomous_event() -> None:
    now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    plan_state = AutonomousPlanState(
        last_rejected_at=now - timedelta(seconds=2),
        reconsider_after_seconds=10.0,
    )

    result = plan(
        build_planner(plan_state=plan_state),
        AgentState(current_drive=DriveState(curiosity=0.9, energy=0.9)),
        now,
    )

    assert result.event is None
    assert result.skip_reason == "autonomous_plan_retry_backoff"
    assert result.details["backoff_seconds"] == 10.0


def test_early_skip_does_not_evaluate_topic_continuation() -> None:
    now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    continuation_calls = 0

    def continuation_provider():
        nonlocal continuation_calls
        continuation_calls += 1
        return None

    result = build_planner(pending_confirmation=True).plan(
        AgentState(current_drive=DriveState(curiosity=0.9, energy=0.9)),
        now=now,
        awakening_completed_at=None,
        continuation_provider=continuation_provider,
        autonomous_topic_provider=lambda: None,
    )

    assert result.skip_reason == "pending_confirmation_exists"
    assert continuation_calls == 0
