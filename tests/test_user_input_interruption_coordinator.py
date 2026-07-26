from __future__ import annotations

from unittest.mock import MagicMock

from app.domain.activities import Activity, ActivityType
from app.domain.events import AgentEvent, AgentEventType
from app.runtime.user_input_interruption_coordinator import (
    UserInputInterruptionCoordinator,
)


def _coordinator() -> tuple[UserInputInterruptionCoordinator, dict[str, MagicMock]]:
    dependencies = {
        "activity_manager": MagicMock(),
        "action_scheduler": MagicMock(),
        "activity_planner_thread": MagicMock(),
        "activity_executor_thread": MagicMock(),
        "agent_life_service": MagicMock(),
        "trace_logger": MagicMock(),
    }
    return (
        UserInputInterruptionCoordinator(**dependencies),  # type: ignore[arg-type]
        dependencies,
    )


def test_before_routing_cancels_segments_for_foreground_autonomous_talk() -> None:
    coordinator, dependencies = _coordinator()
    autonomous = Activity(
        activity_type=ActivityType.AUTONOMOUS_TALK,
        goal="海の話を続ける",
    )
    event = AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"text": "こんにちは"},
    )

    coordinator.before_routing(event, foreground_at_receipt=autonomous)

    dependencies["action_scheduler"].cancel_pending_segments.assert_called_once_with(
        autonomous.activity_id
    )


def test_before_routing_ignores_non_user_text() -> None:
    coordinator, dependencies = _coordinator()
    autonomous = Activity(
        activity_type=ActivityType.AUTONOMOUS_TALK,
        goal="海の話を続ける",
    )

    coordinator.before_routing(
        AgentEvent(event_type=AgentEventType.CURIOSITY_PEAK),
        foreground_at_receipt=autonomous,
    )

    dependencies["action_scheduler"].cancel_pending_segments.assert_not_called()


def test_after_prioritization_interrupts_autonomous_work_and_syncs() -> None:
    coordinator, dependencies = _coordinator()
    autonomous = Activity(
        activity_type=ActivityType.AUTONOMOUS_TALK,
        goal="海の話を続ける",
    )
    conversation = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="ユーザーと会話する",
    )
    event = AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"text": "こんにちは"},
    )
    dependencies["activity_manager"].prepare_user_input.return_value = conversation
    dependencies["activity_manager"].discard_deferred_autonomous.return_value = []
    dependencies[
        "activity_executor_thread"
    ].cancel_pending_autonomous.return_value = []

    result = coordinator.after_prioritization(
        event,
        foreground_at_receipt=autonomous,
    )

    assert result == conversation
    dependencies["activity_manager"].prepare_user_input.assert_called_once_with(event)
    dependencies[
        "activity_planner_thread"
    ].cancel_inflight_autonomous.assert_called_once_with(
        source_event_id=event.event_id,
        trace_context=event.trace_context,
    )
    dependencies[
        "agent_life_service"
    ].interrupt_autonomous_topic.assert_called_once_with(
        activity_id=autonomous.activity_id,
        fallback_text=autonomous.goal,
    )
    dependencies[
        "activity_manager"
    ].discard_deferred_autonomous.assert_called_once_with(
        reason="user_conversation_started"
    )
    dependencies[
        "activity_executor_thread"
    ].cancel_pending_autonomous.assert_called_once_with(
        source_event_id=event.event_id,
        reason="user_text_received",
    )
    dependencies["agent_life_service"].sync_from_activity_manager.assert_called_once()


def test_after_prioritization_only_prepares_non_user_event() -> None:
    coordinator, dependencies = _coordinator()
    event = AgentEvent(event_type=AgentEventType.CURIOSITY_PEAK)
    dependencies["activity_manager"].prepare_user_input.return_value = None

    result = coordinator.after_prioritization(
        event,
        foreground_at_receipt=None,
    )

    assert result is None
    dependencies["activity_manager"].prepare_user_input.assert_called_once_with(event)
    dependencies[
        "activity_planner_thread"
    ].cancel_inflight_autonomous.assert_not_called()
    dependencies[
        "activity_executor_thread"
    ].cancel_pending_autonomous.assert_not_called()
    dependencies["agent_life_service"].sync_from_activity_manager.assert_not_called()
