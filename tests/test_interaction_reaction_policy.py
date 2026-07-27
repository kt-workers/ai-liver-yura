from datetime import datetime, timedelta, timezone

from app.domain.events import AgentEvent, AgentEventType
from app.domain.memory import AgentMemoryState, EmotionHistoryEntry
from app.runtime.agent_state import AgentState
from app.runtime.interaction_reaction_policy import InteractionReactionPolicy


def _interaction(
    occurred_at: datetime,
    *,
    burst_count: int = 1,
) -> AgentEvent:
    return AgentEvent(
        event_type=AgentEventType.USER_INTERACTION,
        occurred_at=occurred_at,
        payload={
            "stimulus_kind": "tap",
            "interaction_burst_count": burst_count,
        },
    )


def _state_for(event: AgentEvent, reason: str = "") -> AgentState:
    if not reason:
        return AgentState()
    return AgentState(
        memory=AgentMemoryState(
            emotion_history=(
                EmotionHistoryEntry(
                    source_event_id=event.event_id,
                    before={},
                    after={},
                    reason=reason,
                    recorded_at=event.occurred_at,
                ),
            )
        )
    )


def test_policy_suppresses_repeated_speech_during_contact_burst() -> None:
    started_at = datetime(2026, 7, 27, tzinfo=timezone.utc)
    policy = InteractionReactionPolicy(verbal_cooldown_seconds=10.0)

    first = _interaction(started_at)
    second = _interaction(started_at + timedelta(seconds=2), burst_count=2)
    third = _interaction(started_at + timedelta(seconds=11), burst_count=1)

    assert policy.should_speak(first, _state_for(first)) is True
    assert (
        policy.should_speak(
            second,
            _state_for(second),
        )
        is False
    )
    assert (
        policy.should_speak(
            third,
            _state_for(third),
        )
        is True
    )


def test_policy_expresses_boundary_then_waits_before_followup() -> None:
    started_at = datetime(2026, 7, 27, tzinfo=timezone.utc)
    policy = InteractionReactionPolicy(
        verbal_cooldown_seconds=12.0,
        boundary_followup_cooldown_seconds=8.0,
    )
    first = _interaction(started_at)
    boundary = _interaction(started_at + timedelta(seconds=2), burst_count=6)
    ignored_soon = _interaction(
        started_at + timedelta(seconds=5),
        burst_count=7,
    )
    ignored_later = _interaction(
        started_at + timedelta(seconds=11),
        burst_count=8,
    )

    assert policy.should_speak(first, _state_for(first)) is True
    assert (
        policy.should_speak(
            boundary,
            _state_for(boundary, "contact_boundary_requested"),
        )
        is True
    )
    assert (
        policy.should_speak(
            ignored_soon,
            _state_for(ignored_soon, "contact_boundary_ignored"),
        )
        is False
    )
    assert (
        policy.should_speak(
            ignored_later,
            _state_for(ignored_later, "contact_boundary_ignored"),
        )
        is True
    )
