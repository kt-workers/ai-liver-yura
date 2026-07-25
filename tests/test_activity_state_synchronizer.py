from __future__ import annotations

from datetime import datetime, timezone

from app.domain.events import AgentEvent, AgentEventType
from app.domain.topic import InterruptedTopic, TopicLifecycleStatus
from app.runtime.activity_manager import ActivityManager
from app.runtime.activity_state_synchronizer import ActivityStateSynchronizer
from app.runtime.agent_state import AgentState


def test_synchronize_reflects_foreground_activity_and_unfinished_memory() -> None:
    manager = ActivityManager()
    event = AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"text": "こんにちは"},
    )
    activity = manager.handle_event(event)

    state = ActivityStateSynchronizer(manager).synchronize(AgentState())

    assert state.active_activity is not None
    assert state.active_activity.activity_id == activity.activity_id
    assert state.current_situation.active_activity_id == activity.activity_id
    assert state.current_situation.active_activity_type == activity.activity_type.value
    assert [item.activity_id for item in state.memory.unfinished_activities] == [
        activity.activity_id
    ]


def test_synchronize_reflects_ongoing_activity_snapshot() -> None:
    manager = ActivityManager()
    ongoing = manager.start_ongoing_activity(
        activity_type="conversation",
        goal="会話を続ける",
        expected_input="ユーザー入力",
        end_condition="会話終了",
    )

    state = ActivityStateSynchronizer(manager).synchronize(AgentState())

    assert state.current_situation.ongoing_activity_id == ongoing.ongoing_activity_id
    assert state.current_situation.ongoing_activity_type == ongoing.activity_type
    assert state.current_situation.ongoing_activity_status == ongoing.status.value


def test_synchronize_records_interrupted_topic_as_unrecovered_memory() -> None:
    manager = ActivityManager()
    interrupted_at = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
    topic = InterruptedTopic(
        topic_id="topic-1",
        source_activity_id="activity-1",
        original_text="話題の続き",
        status=TopicLifecycleStatus.INTERRUPTED,
        importance=0.8,
        interrupted_at=interrupted_at,
    )

    state = ActivityStateSynchronizer(manager).synchronize(
        AgentState(),
        autonomous_topic=topic,
    )

    unrecovered = state.memory.unrecovered_topic
    assert unrecovered is not None
    assert unrecovered.topic_id == "topic-1"
    assert unrecovered.source_activity_id == "activity-1"
    assert unrecovered.summary == "話題の続き"
    assert unrecovered.interrupted_at == interrupted_at


def test_synchronize_clears_unrecovered_memory_for_completed_topic() -> None:
    manager = ActivityManager()
    interrupted = InterruptedTopic(
        topic_id="topic-1",
        source_activity_id="activity-1",
        original_text="話題の続き",
        status=TopicLifecycleStatus.INTERRUPTED,
    )
    synchronizer = ActivityStateSynchronizer(manager)
    state = synchronizer.synchronize(AgentState(), autonomous_topic=interrupted)
    completed = interrupted.with_status(TopicLifecycleStatus.COMPLETED)

    updated = synchronizer.synchronize(state, autonomous_topic=completed)

    assert updated.memory.unrecovered_topic is None
