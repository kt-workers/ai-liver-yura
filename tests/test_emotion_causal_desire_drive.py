from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.domain.desires import DesireState
from app.domain.drives import DriveState
from app.domain.emotions import EmotionAppraisal, EmotionCause, EmotionState
from app.domain.events import AgentEvent, AgentEventType
from app.runtime.affective_appraisal_observer import AffectiveAppraisalObserver
from app.runtime.agent_event_state_updater import AgentEventStateUpdater
from app.runtime.agent_state import AgentState
from app.runtime.causal_emotion_appraiser import CausalEmotionAppraiser
from app.runtime.desire_state_updater import DesireStateUpdater
from app.runtime.drive_state_updater import DriveStateUpdater
from app.runtime.elapsed_state_updater import ElapsedStateUpdater
from app.runtime.emotion_state_updater import EmotionStateUpdater


def _observe(
    event: AgentEvent,
    appraisal: EmotionAppraisal,
    *,
    before: EmotionState | None = None,
):
    before_state = before or EmotionState()
    updater = EmotionStateUpdater()
    after = updater.apply(before_state, appraisal)
    affective, comparison = AffectiveAppraisalObserver(
        emotion_state_updater=updater
    ).observe(
        event,
        legacy_appraisal=appraisal,
        before_emotion=before_state,
        actual_after_emotion=after,
        relationship=None,
    )
    assert comparison.matched is True
    return before_state, after, affective


def test_silence_event_does_not_directly_raise_desire_without_emotion() -> None:
    desire = DesireState()
    event = AgentEvent(event_type=AgentEventType.SILENCE_TIMEOUT)
    before_emotion, after_emotion, affective = _observe(
        event,
        EmotionAppraisal(source_event_id=event.event_id),
    )

    updated = DesireStateUpdater().update_from_affect(
        desire,
        event,
        affective_appraisal=affective,
        before_emotion=before_emotion,
        after_emotion=after_emotion,
    )

    assert updated == desire
    assert DesireStateUpdater().update_by_event(desire, event) != desire


def test_fear_and_discomfort_raise_security_desire_through_affect() -> None:
    desire = DesireState()
    event = AgentEvent(event_type=AgentEventType.USER_INTERACTION)
    appraisal = EmotionAppraisal(
        fear_delta=0.18,
        discomfort_delta=0.22,
        pressure_delta=0.12,
        valence_delta=-0.15,
        reason="unexpected_uncomfortable_contact",
        cause=EmotionCause(
            category="unexpected_uncomfortable_contact",
            summary="予期しない不快な接触として受け止めた",
            source_event_id=event.event_id,
        ),
        source_event_id=event.event_id,
    )
    before_emotion, after_emotion, affective = _observe(event, appraisal)

    updated = DesireStateUpdater().update_from_affect(
        desire,
        event,
        affective_appraisal=affective,
        before_emotion=before_emotion,
        after_emotion=after_emotion,
    )

    assert updated.security.level > desire.security.level
    assert updated.expression.level > desire.expression.level


def test_trend_stimulus_reaches_curiosity_through_emotion() -> None:
    event = AgentEvent(event_type=AgentEventType.TREND_UPDATED)
    result = AgentEventStateUpdater().update(AgentState(), event)

    assert result.appraisal.reason == "new_external_stimulus_observed"
    assert result.after_emotion.reactive.surprise > result.before_emotion.reactive.surprise
    assert result.after_desire.curiosity.level > result.before_desire.curiosity.level
    assert result.after_drive.curiosity >= result.after_desire.curiosity.effective_level


def test_activity_failure_updates_emotion_before_desire_result() -> None:
    event = AgentEvent(
        event_type=AgentEventType.ACTIVITY_RESULT_RECORDED,
        payload={
            "activity_id": "activity-1",
            "activity_type": "topic_exploration",
            "outcome": "failed",
        },
    )

    result = AgentEventStateUpdater().update(AgentState(), event)

    assert result.appraisal.reason == "activity_failed"
    assert result.after_emotion.reactive.discomfort > 0.0
    assert result.after_desire.achievement.frustration > 0.0
    assert result.after_desire.curiosity.frustration > 0.0
    assert result.after_desire.security.level > result.before_desire.security.level


def test_drive_curiosity_is_compatibility_projection_of_desire() -> None:
    event = AgentEvent(event_type=AgentEventType.CAMERA_FRAME)
    appraisal = EmotionAppraisal(source_event_id=event.event_id)
    before_emotion, after_emotion, affective = _observe(event, appraisal)
    desire = DesireState().with_value(
        desire_type=next(
            desire_type
            for desire_type in __import__(
                "app.domain.desires", fromlist=["DesireType"]
            ).DesireType
            if desire_type.value == "curiosity"
        ),
        value=DesireState().curiosity.adjusted(level_delta=0.20),
    )

    updated = DriveStateUpdater().derive_from_affect(
        DriveState(curiosity=0.1),
        event,
        affective_appraisal=affective,
        emotion=after_emotion,
        desire=desire,
        activity_active=False,
    )

    assert updated.curiosity == pytest.approx(desire.curiosity.effective_level)
    assert before_emotion == after_emotion


def test_elapsed_drive_uses_emotion_desire_and_activity_cost() -> None:
    now = datetime(2026, 8, 6, 3, 0, tzinfo=timezone.utc)
    updater = ElapsedStateUpdater(initial_time=now)
    state = AgentState(
        current_drive=DriveState(curiosity=0.2, engagement=0.8, boredom=0.1, energy=0.4),
        current_emotion=EmotionState(arousal=0.2, valence=0.0),
    )

    result = updater.update(state, now=now + timedelta(minutes=10))

    assert result.after_drive.curiosity > result.before_drive.curiosity
    assert result.after_drive.energy > result.before_drive.energy
    assert result.after_drive.curiosity <= result.after_desire.curiosity.effective_level


def test_causal_emotion_appraiser_keeps_legacy_path_for_regular_events() -> None:
    event = AgentEvent(event_type=AgentEventType.USER_TEXT, payload={"text": "こんにちは"})

    appraisal = CausalEmotionAppraiser().appraise(event)

    assert appraisal.reason == "user_attention_received"
    assert appraisal.arousal_delta > 0.0
