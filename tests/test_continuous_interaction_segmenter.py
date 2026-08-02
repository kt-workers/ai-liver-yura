from datetime import datetime, timedelta, timezone

from app.domain.events import AgentEvent, AgentEventType
from app.runtime.continuous_interaction_segmenter import ContinuousInteractionSegmenter


def _drag(
    occurred_at: datetime,
    phase: str,
    *,
    gesture_id: str = "drag-1",
) -> AgentEvent:
    return AgentEvent(
        event_type=AgentEventType.USER_INTERACTION,
        occurred_at=occurred_at,
        payload={
            "stimulus_kind": "drag",
            "gesture_id": gesture_id,
            "gesture_phase": phase,
            "continuous_contact": True,
        },
    )


def test_continuous_contact_is_applied_at_one_second_segments() -> None:
    started_at = datetime(2026, 8, 2, tzinfo=timezone.utc)
    segmenter = ContinuousInteractionSegmenter(interval_seconds=1.0)

    started = segmenter.decide(_drag(started_at, "start"))
    early = segmenter.decide(_drag(started_at + timedelta(seconds=0.2), "update"))
    first_segment = segmenter.decide(
        _drag(started_at + timedelta(seconds=1.05), "update")
    )
    within_second_segment = segmenter.decide(
        _drag(started_at + timedelta(seconds=1.6), "update")
    )
    second_segment = segmenter.decide(
        _drag(started_at + timedelta(seconds=2.1), "update")
    )
    ended = segmenter.decide(_drag(started_at + timedelta(seconds=2.2), "end"))

    assert started.should_apply is True
    assert started.weight == 0.35
    assert started.segment_index == 0
    assert early.should_apply is False
    assert first_segment.should_apply is True
    assert first_segment.weight == 0.35
    assert first_segment.segment_index == 1
    assert within_second_segment.should_apply is False
    assert second_segment.should_apply is True
    assert second_segment.segment_index == 2
    assert ended.should_apply is True
    assert ended.weight == 0.15
    assert ended.segment_index == 3


def test_new_gesture_after_end_starts_from_first_segment() -> None:
    started_at = datetime(2026, 8, 2, tzinfo=timezone.utc)
    segmenter = ContinuousInteractionSegmenter(interval_seconds=1.0)

    segmenter.decide(_drag(started_at, "start"))
    segmenter.decide(_drag(started_at + timedelta(seconds=0.5), "end"))
    restarted = segmenter.decide(
        _drag(started_at + timedelta(seconds=2.0), "start")
    )

    assert restarted.should_apply is True
    assert restarted.segment_index == 0


def test_non_continuous_interaction_is_not_segmented() -> None:
    segmenter = ContinuousInteractionSegmenter(interval_seconds=1.0)
    event = AgentEvent(
        event_type=AgentEventType.USER_INTERACTION,
        payload={"stimulus_kind": "tap"},
    )

    decision = segmenter.decide(event)

    assert decision.should_apply is True
    assert decision.weight is None
