from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.runtime.conversation_resume_state import ConversationResumeState


def test_explicit_end_reason_has_priority_and_is_normalized() -> None:
    now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    state = ConversationResumeState(observed_ongoing_activity_id="ongoing-1")

    state.end_conversation("  user_finished  ")

    assert state.resolve_reason(
        last_user_input_at=now - timedelta(minutes=10),
        now=now,
        idle_timeout_seconds=30.0,
    ) == "conversation_ended:user_finished"


def test_ongoing_activity_completion_is_used_after_observation() -> None:
    now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    state = ConversationResumeState()

    state.observe_ongoing_activity("ongoing-1")

    assert state.resolve_reason(
        last_user_input_at=now,
        now=now,
        idle_timeout_seconds=30.0,
    ) == "ongoing_activity_completed:ongoing-1"


def test_idle_timeout_and_no_conversation_are_resolved() -> None:
    now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    state = ConversationResumeState()

    assert state.resolve_reason(
        last_user_input_at=now - timedelta(seconds=30),
        now=now,
        idle_timeout_seconds=30.0,
    ) == "conversation_idle_timeout"
    assert state.resolve_reason(
        last_user_input_at=now - timedelta(seconds=29),
        now=now,
        idle_timeout_seconds=30.0,
    ) is None
    assert state.resolve_reason(
        last_user_input_at=None,
        now=now,
        idle_timeout_seconds=30.0,
    ) == "no_conversation"


def test_plan_acceptance_clears_transient_resume_reasons() -> None:
    state = ConversationResumeState(
        explicit_end_reason="finished",
        observed_ongoing_activity_id="ongoing-1",
    )

    state.clear_after_plan_accepted()

    assert state.explicit_end_reason is None
    assert state.observed_ongoing_activity_id is None


@pytest.mark.parametrize("value", ["", "   "])
def test_blank_reasons_and_ids_are_rejected(value: str) -> None:
    state = ConversationResumeState()

    with pytest.raises(ValueError):
        state.end_conversation(value)
    with pytest.raises(ValueError):
        state.observe_ongoing_activity(value)
