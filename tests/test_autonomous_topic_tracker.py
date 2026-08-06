from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domain.autonomous_continuation import AutonomousContinuationAction
from app.domain.drives import DriveState
from app.domain.emotions import EmotionState
from app.domain.topic import TopicLifecycleStatus
from app.runtime.autonomous_topic_tracker import AutonomousTopicTracker


def test_record_output_creates_topic_with_default_metrics() -> None:
    tracker = AutonomousTopicTracker(uuid_factory=lambda: "topic-1")

    topic = tracker.record_output(
        activity_id="activity-1",
        text="まず深海魚について話すね",
        drive=DriveState(curiosity=0.8, engagement=0.5),
        emotion=EmotionState(),
    )

    assert topic.topic_id == "topic-1"
    assert topic.source_activity_id == "activity-1"
    assert topic.status is TopicLifecycleStatus.ACTIVE
    assert topic.interest == pytest.approx(0.68)
    assert topic.incompleteness == pytest.approx(0.85)
    assert topic.exhaustion == 0.0
    assert topic.turn_count == 1


def test_record_output_updates_existing_topic_without_changing_id() -> None:
    tracker = AutonomousTopicTracker(uuid_factory=lambda: "topic-1")
    drive = DriveState(curiosity=0.8, engagement=0.5, energy=0.7)
    emotion = EmotionState()
    first = tracker.record_output(
        activity_id="activity-1",
        text="深海魚について話すね",
        drive=drive,
        emotion=emotion,
        context={
            "topic_metrics": {
                "interest": 0.8,
                "incompleteness": 0.7,
                "exhaustion": 0.1,
                "importance": 0.6,
            }
        },
    )

    second = tracker.record_output(
        activity_id="activity-1",
        text="深海魚について話すね",
        drive=drive,
        emotion=emotion,
        context={
            "topic_metrics": {
                "interest": 0.8,
                "incompleteness": 0.7,
                "exhaustion": 0.1,
                "importance": 0.6,
            }
        },
    )

    assert second.topic_id == first.topic_id
    assert second.turn_count == 2
    assert second.interest == pytest.approx(0.71)
    assert second.incompleteness == pytest.approx(0.62)
    assert second.exhaustion == pytest.approx(0.297)


def test_should_complete_returns_strength_and_decision() -> None:
    tracker = AutonomousTopicTracker(uuid_factory=lambda: "topic-1")
    drive = DriveState(curiosity=0.0, engagement=0.0, energy=0.0)
    emotion = EmotionState(talkativeness=0.0, arousal=0.0)
    tracker.record_output(
        activity_id="activity-1",
        text="話題",
        drive=drive,
        emotion=emotion,
        context={
            "topic_metrics": {
                "interest": 0.0,
                "incompleteness": 0.0,
                "exhaustion": 1.0,
            }
        },
    )
    tracker.record_output(
        activity_id="activity-1",
        text="話題",
        drive=drive,
        emotion=emotion,
        context={
            "topic_metrics": {
                "interest": 0.0,
                "incompleteness": 0.0,
                "exhaustion": 1.0,
            }
        },
    )

    should_complete, strength = tracker.should_complete(
        activity_id="activity-1",
        drive=drive,
        emotion=emotion,
    )

    assert should_complete is True
    assert strength is not None
    assert strength <= 0.20


def test_question_returns_turn_to_user_after_first_output() -> None:
    tracker = AutonomousTopicTracker(uuid_factory=lambda: "topic-1")
    drive = DriveState(curiosity=0.9, engagement=0.9, energy=0.9)
    emotion = EmotionState(talkativeness=0.9, arousal=0.8)
    tracker.record_output(
        activity_id="activity-1",
        text="最近どんなゲームが気になっている？",
        drive=drive,
        emotion=emotion,
    )

    evaluation = tracker.evaluate_completion(
        activity_id="activity-1",
        drive=drive,
        emotion=emotion,
    )

    assert evaluation is not None
    assert evaluation.action is AutonomousContinuationAction.COMPLETE
    assert evaluation.reason == "user_response_expected_after_question"
    assert evaluation.turn_count == 1
    assert evaluation.waiting_for_user is True


def test_autonomous_topic_completes_at_hard_turn_limit() -> None:
    tracker = AutonomousTopicTracker(
        uuid_factory=lambda: "topic-1",
        maximum_autonomous_turns=3,
    )
    drive = DriveState(curiosity=0.9, engagement=0.9, energy=0.9)
    emotion = EmotionState(talkativeness=0.9, arousal=0.8)
    for index in range(3):
        tracker.record_output(
            activity_id="activity-1",
            text=f"未完の話題を続ける {index}",
            drive=drive,
            emotion=emotion,
            context={
                "topic_metrics": {
                    "interest": 1.0,
                    "incompleteness": 1.0,
                    "exhaustion": 0.0,
                }
            },
        )

    evaluation = tracker.evaluate_completion(
        activity_id="activity-1",
        drive=drive,
        emotion=emotion,
    )

    assert evaluation is not None
    assert evaluation.action is AutonomousContinuationAction.COMPLETE
    assert evaluation.reason == "maximum_autonomous_turns_reached"
    assert evaluation.hard_limit_reached is True


def test_non_question_with_strength_can_continue_before_limit() -> None:
    tracker = AutonomousTopicTracker(uuid_factory=lambda: "topic-1")
    drive = DriveState(curiosity=0.9, engagement=0.9, energy=0.9)
    emotion = EmotionState(talkativeness=0.9, arousal=0.8)
    tracker.record_output(
        activity_id="activity-1",
        text="まず一つ目の考えを話すね",
        drive=drive,
        emotion=emotion,
    )

    evaluation = tracker.evaluate_completion(
        activity_id="activity-1",
        drive=drive,
        emotion=emotion,
    )

    assert evaluation is not None
    assert evaluation.action is AutonomousContinuationAction.CONTINUE
    assert evaluation.reason == "topic_still_has_causal_continuation_strength"


def test_invalid_maximum_autonomous_turns_is_rejected() -> None:
    with pytest.raises(ValueError):
        AutonomousTopicTracker(maximum_autonomous_turns=0)


def test_interrupt_preserves_existing_topic_identity() -> None:
    tracker = AutonomousTopicTracker(uuid_factory=lambda: "topic-1")
    tracker.record_output(
        activity_id="activity-1",
        text="元の話題",
        drive=DriveState(),
        emotion=EmotionState(),
    )
    interrupted_at = datetime(2026, 7, 25, tzinfo=timezone.utc)

    interrupted = tracker.interrupt(
        activity_id="activity-1",
        fallback_text="予備",
        now=interrupted_at,
    )

    assert interrupted.topic_id == "topic-1"
    assert interrupted.status is TopicLifecycleStatus.INTERRUPTED
    assert interrupted.interrupted_at == interrupted_at


def test_complete_keeps_only_last_five_autonomous_texts() -> None:
    counter = 0

    def next_id() -> str:
        nonlocal counter
        counter += 1
        return f"topic-{counter}"

    tracker = AutonomousTopicTracker(uuid_factory=next_id)
    for index in range(6):
        activity_id = f"activity-{index}"
        tracker.record_output(
            activity_id=activity_id,
            text=f"話題{index}",
            drive=DriveState(),
            emotion=EmotionState(),
        )
        tracker.complete(activity_id=activity_id)

    assert tracker.recent_autonomous_texts == (
        "話題1",
        "話題2",
        "話題3",
        "話題4",
        "話題5",
    )


def test_explicit_continuation_request_is_not_counted_as_interruption() -> None:
    tracker = AutonomousTopicTracker(uuid_factory=lambda: "topic-1")
    tracker.record_output(
        activity_id="activity-1",
        text="元の話題",
        drive=DriveState(),
        emotion=EmotionState(),
    )

    topic = tracker.add_interruption_topic("続きを聞きたい")

    assert topic is not None
    assert topic.interruption_turns == 0
    assert topic.interruption_topics == ()
