from __future__ import annotations

from datetime import datetime, timezone

from app.domain.topic import TopicLifecycleStatus
from app.runtime.activity_manager import ActivityManager
from app.runtime.agent_life_service import AgentLifeService
from app.runtime.autonomous_topic_tracker import AutonomousTopicTracker
from app.runtime.topic_tracking_agent_life_service import TopicTrackingAgentLifeService


def create_service() -> TopicTrackingAgentLifeService:
    return TopicTrackingAgentLifeService(
        ActivityManager(),
        autonomous_topic_tracker=AutonomousTopicTracker(
            uuid_factory=lambda: "topic-1"
        ),
    )


def test_upgrade_existing_preserves_object_identity_and_state() -> None:
    original = AgentLifeService(ActivityManager())
    original.record_autonomous_output(
        activity_id="activity-1",
        text="元の話題",
    )
    original_id = id(original)
    original_topic = original.autonomous_topic

    upgraded = TopicTrackingAgentLifeService.upgrade_existing(
        original,
        autonomous_topic_tracker=AutonomousTopicTracker(
            uuid_factory=lambda: "topic-2"
        ),
    )

    assert id(upgraded) == original_id
    assert isinstance(upgraded, TopicTrackingAgentLifeService)
    assert upgraded.autonomous_topic == original_topic


def test_record_autonomous_output_delegates_to_topic_tracker() -> None:
    service = create_service()

    topic = service.record_autonomous_output(
        activity_id="activity-1",
        text="まず深海魚について話すね",
    )

    assert topic.topic_id == "topic-1"
    assert topic.turn_count == 1
    assert service.autonomous_topic == topic


def test_repeated_output_preserves_topic_identity_through_facade() -> None:
    service = create_service()

    first = service.record_autonomous_output(
        activity_id="activity-1",
        text="深海魚について話すね",
    )
    second = service.record_autonomous_output(
        activity_id="activity-1",
        text="深海魚について話すね",
    )

    assert second.topic_id == first.topic_id
    assert second.turn_count == 2


def test_interrupt_and_complete_keep_legacy_state_synchronized() -> None:
    service = create_service()
    service.record_autonomous_output(
        activity_id="activity-1",
        text="深海魚について話すね",
    )
    interrupted_at = datetime(2026, 7, 25, tzinfo=timezone.utc)

    interrupted = service.interrupt_autonomous_topic(
        activity_id="activity-1",
        fallback_text="予備の話題",
        now=interrupted_at,
    )
    service.complete_autonomous_topic(activity_id="activity-1")

    assert interrupted.status is TopicLifecycleStatus.INTERRUPTED
    assert interrupted.interrupted_at == interrupted_at
    assert service.autonomous_topic == interrupted


def test_should_complete_uses_tracker_metrics() -> None:
    service = create_service()
    metrics = {
        "topic_metrics": {
            "interest": 0.0,
            "incompleteness": 0.0,
            "exhaustion": 1.0,
        }
    }
    service.record_autonomous_output(
        activity_id="activity-1",
        text="話題",
        context=metrics,
    )
    service.record_autonomous_output(
        activity_id="activity-1",
        text="話題",
        context=metrics,
    )

    assert service.should_complete_autonomous_activity(activity_id="activity-1") is True
