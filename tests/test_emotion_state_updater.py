from dataclasses import asdict
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.emotions import (
    EmotionAppraisal,
    EmotionState,
    MoodType,
    ReactiveEmotionState,
    RelationalMeaning,
)
from app.domain.events import AgentEvent, AgentEventType
from app.domain.memory import EmotionHistoryEntry
from app.domain.relationships import RelationshipState
from app.runtime import ActivityManager, AgentLifeService
from app.runtime.agent_event_state_updater import AgentEventStateUpdater
from app.runtime.agent_state import AgentState
from app.runtime.emotion_appraiser import EmotionAppraiser
from app.runtime.emotion_context_builder import EmotionContextBuilder
from app.runtime.emotion_state_updater import EmotionStateUpdater


def test_emotion_state_updater_applies_deltas_with_range_guarantees() -> None:
    state = EmotionState(arousal=0.98, valence=-0.97, talkativeness=0.99)

    updated = EmotionStateUpdater().apply(
        state,
        EmotionAppraisal(
            arousal_delta=0.2,
            valence_delta=-0.2,
            talkativeness_delta=0.2,
            reason="test",
        ),
    )

    assert updated.arousal == 1.0
    assert updated.valence == -1.0
    assert updated.talkativeness == 1.0


def test_emotion_state_updater_decays_toward_baseline_and_preserves_mood_until_settled() -> (
    None
):
    updater = EmotionStateUpdater()
    state = EmotionState(
        mood=MoodType.EXCITED,
        arousal=1.0,
        valence=0.8,
        talkativeness=0.9,
    )

    halfway = updater.decay(state, elapsed_seconds=900.0)
    settled = updater.decay(state, elapsed_seconds=1800.0)

    assert halfway == EmotionState(
        mood=MoodType.EXCITED,
        arousal=0.75,
        valence=0.4,
        talkativeness=0.7,
    )
    assert settled == EmotionState()


def test_emotion_appraiser_uses_event_fact_without_inferring_user_sentiment() -> None:
    appraisal = EmotionAppraiser().appraise(
        AgentEvent(
            event_type=AgentEventType.USER_TEXT,
            payload={"text": "最悪だし腹が立つ"},
        )
    )

    assert appraisal.reason == "user_attention_received"
    assert appraisal.valence_delta == 0.0
    assert appraisal.arousal_delta > 0.0


def test_emotion_appraiser_treats_visualizer_tap_as_gentle_surprise() -> None:
    appraisal = EmotionAppraiser().appraise(
        AgentEvent(
            event_type=AgentEventType.USER_INTERACTION,
            payload={"stimulus_kind": "tap"},
        )
    )

    assert appraisal.reason == "contact_affection_received"
    assert appraisal.cause is not None
    assert appraisal.cause.summary == "触れ合いに親しさを感じた"
    assert appraisal.surprise_delta > 0.0
    assert appraisal.joy_delta > 0.0
    assert appraisal.arousal_delta > 0.0
    assert appraisal.valence_delta > 0.0


def test_repeated_lower_contact_requests_boundary_without_immediate_anger() -> None:
    appraisal = EmotionAppraiser().appraise(
        AgentEvent(
            event_type=AgentEventType.USER_INTERACTION,
            payload={
                "stimulus_kind": "long_press",
                "contact_region": "lower",
                "interaction_burst_count": 10,
                "duration_ms": 3000,
            },
        ),
        current_emotion=EmotionState(
            arousal=0.9,
            valence=0.1,
            reactive=ReactiveEmotionState(discomfort=0.18),
        ),
    )

    assert appraisal.reason == "contact_boundary_requested"
    assert appraisal.discomfort_delta > 0.0
    assert appraisal.pressure_delta > 0.0
    assert appraisal.anger_delta == 0.0
    assert appraisal.valence_delta < 0.0
    assert appraisal.cause is not None
    assert appraisal.cause.target == "lower"


def test_calm_first_contact_at_center_can_be_pleasant() -> None:
    appraisal = EmotionAppraiser().appraise(
        AgentEvent(
            event_type=AgentEventType.USER_INTERACTION,
            payload={
                "stimulus_kind": "long_press",
                "contact_region": "center",
                "interaction_burst_count": 1,
            },
        ),
        current_emotion=EmotionState(arousal=0.4, valence=0.1),
    )

    assert appraisal.joy_delta > 0.0
    assert appraisal.discomfort_delta == 0.0
    assert appraisal.valence_delta > 0.0


@pytest.mark.parametrize(
    ("kind", "reason"),
    [
        ("double_tap", "contact_affection_received"),
        ("long_press", "contact_comfort_received"),
        ("drag", "contact_affection_received"),
    ],
)
def test_emotion_appraiser_distinguishes_visualizer_gestures(
    kind: str,
    reason: str,
) -> None:
    appraisal = EmotionAppraiser().appraise(
        AgentEvent(
            event_type=AgentEventType.USER_INTERACTION,
            payload={"stimulus_kind": kind},
        )
    )

    assert appraisal.reason == reason
    assert appraisal.cause is not None
    assert appraisal.cause.summary
    assert appraisal.valence_delta > 0.0


def test_trusted_contact_can_restore_comfort_and_positive_feeling() -> None:
    appraisal = EmotionAppraiser().appraise(
        AgentEvent(
            event_type=AgentEventType.USER_INTERACTION,
            payload={
                "stimulus_kind": "long_press",
                "contact_region": "center",
            },
        ),
        current_emotion=EmotionState(
            arousal=0.65,
            reactive=ReactiveEmotionState(
                discomfort=0.06,
                emotional_pressure=0.05,
            ),
        ),
        relationship=RelationshipState(
            counterpart_id="owner",
            display_name="owner",
            trust=0.9,
            affinity=0.8,
            familiarity=0.7,
        ),
    )

    assert appraisal.reason == "contact_comfort_received"
    assert appraisal.joy_delta > 0.0
    assert appraisal.discomfort_delta < 0.0
    assert appraisal.pressure_delta < 0.0
    assert appraisal.valence_delta > 0.0


def test_same_contact_can_feel_uncomfortable_when_trust_is_low() -> None:
    appraisal = EmotionAppraiser().appraise(
        AgentEvent(
            event_type=AgentEventType.USER_INTERACTION,
            payload={
                "stimulus_kind": "long_press",
                "contact_region": "lower",
            },
        ),
        current_emotion=EmotionState(arousal=0.65),
        relationship=RelationshipState(
            counterpart_id="visitor",
            display_name="visitor",
            trust=0.1,
            affinity=-0.5,
            familiarity=0.0,
        ),
    )

    assert appraisal.reason == "contact_overstimulating"
    assert appraisal.discomfort_delta > 0.0
    assert appraisal.anger_delta == 0.0
    assert appraisal.valence_delta < 0.0


def test_anger_starts_only_after_expressed_boundary_is_repeatedly_ignored() -> None:
    started_at = datetime(2026, 7, 27, tzinfo=timezone.utc)
    updater = AgentEventStateUpdater()
    state = AgentState(
        current_emotion=EmotionState(
            arousal=0.9,
            reactive=ReactiveEmotionState(discomfort=0.18),
        )
    )

    def contact(second: int) -> AgentEvent:
        return AgentEvent(
            event_type=AgentEventType.USER_INTERACTION,
            occurred_at=started_at + timedelta(seconds=second),
            payload={
                "stimulus_kind": "long_press",
                "contact_region": "lower",
                "interaction_burst_count": 10,
                "duration_ms": 3000,
            },
        )

    requested = updater.update(state, contact(0))
    first_ignored = updater.update(requested.state, contact(2))
    second_ignored = updater.update(first_ignored.state, contact(4))

    assert requested.appraisal.reason == "contact_boundary_requested"
    assert requested.appraisal.anger_delta == 0.0
    assert first_ignored.appraisal.reason == "contact_boundary_ignored"
    assert first_ignored.appraisal.anger_delta == 0.0
    assert second_ignored.appraisal.reason == "contact_boundary_ignored"
    assert second_ignored.appraisal.anger_delta > 0.0


def test_contact_after_a_pause_is_guarded_instead_of_immediate_violation() -> None:
    started_at = datetime(2026, 7, 27, tzinfo=timezone.utc)
    updater = AgentEventStateUpdater()
    state = AgentState(
        current_emotion=EmotionState(
            arousal=0.9,
            reactive=ReactiveEmotionState(discomfort=0.18),
        )
    )
    requested_event = AgentEvent(
        event_type=AgentEventType.USER_INTERACTION,
        occurred_at=started_at,
        payload={
            "stimulus_kind": "long_press",
            "contact_region": "lower",
            "interaction_burst_count": 10,
            "duration_ms": 3000,
        },
    )
    requested = updater.update(state, requested_event)
    after_pause = updater.update(
        requested.state,
        AgentEvent(
            event_type=AgentEventType.USER_INTERACTION,
            occurred_at=started_at + timedelta(seconds=40),
            payload={
                "stimulus_kind": "tap",
                "contact_region": "center",
                "interaction_burst_count": 1,
            },
        ),
    )

    assert requested.appraisal.reason == "contact_boundary_requested"
    assert after_pause.appraisal.reason == "contact_boundary_guarded"
    assert after_pause.appraisal.anger_delta == 0.0


def test_structured_repair_meaning_releases_boundary_and_eases_tension() -> None:
    started_at = datetime(2026, 7, 27, tzinfo=timezone.utc)
    updater = AgentEventStateUpdater()
    state = AgentState(
        current_emotion=EmotionState(
            arousal=0.9,
            reactive=ReactiveEmotionState(discomfort=0.18),
        )
    )
    requested = updater.update(
        state,
        AgentEvent(
            event_type=AgentEventType.USER_INTERACTION,
            occurred_at=started_at,
            payload={
                "stimulus_kind": "long_press",
                "contact_region": "lower",
                "interaction_burst_count": 10,
                "duration_ms": 3000,
            },
        ),
    )
    apologized = updater.update(
        requested.state,
        AgentEvent(
            event_type=AgentEventType.USER_TEXT,
            occurred_at=started_at + timedelta(seconds=5),
            payload={
                "text": "……",
                "emotion_appraisal": {
                    "reason": "semantic_relationship_repair",
                    "relational_meaning": "repair_attempt",
                    "confidence": 0.9,
                },
            },
        ),
    )
    next_contact = updater.update(
        apologized.state,
        AgentEvent(
            event_type=AgentEventType.USER_INTERACTION,
            occurred_at=started_at + timedelta(seconds=10),
            payload={
                "stimulus_kind": "tap",
                "contact_region": "center",
                "interaction_burst_count": 1,
            },
        ),
    )

    assert apologized.appraisal.reason == "contact_repair_received"
    assert (
        apologized.appraisal.relational_meaning
        == RelationalMeaning.REPAIR_ATTEMPT
    )
    assert (
        apologized.after_emotion.reactive.discomfort
        < requested.after_emotion.reactive.discomfort
    )
    assert (
        apologized.after_emotion.reactive.emotional_pressure
        < requested.after_emotion.reactive.emotional_pressure
    )
    assert next_contact.appraisal.reason not in {
        "contact_boundary_guarded",
        "contact_boundary_ignored",
    }


def test_specific_apology_word_has_no_core_rule_without_semantic_appraisal() -> None:
    started_at = datetime(2026, 7, 27, tzinfo=timezone.utc)
    updater = AgentEventStateUpdater()
    state = AgentState(
        current_emotion=EmotionState(
            arousal=0.9,
            reactive=ReactiveEmotionState(discomfort=0.18),
        )
    )
    requested = updater.update(
        state,
        AgentEvent(
            event_type=AgentEventType.USER_INTERACTION,
            occurred_at=started_at,
            payload={
                "stimulus_kind": "long_press",
                "contact_region": "lower",
                "interaction_burst_count": 10,
                "duration_ms": 3000,
            },
        ),
    )
    text_result = updater.update(
        requested.state,
        AgentEvent(
            event_type=AgentEventType.USER_TEXT,
            occurred_at=started_at + timedelta(seconds=5),
            payload={"text": "ごめんね"},
        ),
    )

    assert text_result.appraisal.reason == "user_attention_received"
    assert (
        text_result.after_emotion.reactive.discomfort
        == requested.after_emotion.reactive.discomfort
    )


def test_emotion_context_for_event_excludes_later_emotion_changes() -> None:
    occurred_at = datetime(2026, 7, 27, tzinfo=timezone.utc)
    neutral = EmotionState()
    affectionate = EmotionState(
        valence=0.04,
        reactive=ReactiveEmotionState(joy=0.035),
    )
    angry = EmotionState(
        mood=MoodType.ANGRY,
        arousal=0.9,
        valence=-0.4,
        reactive=ReactiveEmotionState(anger=0.4, discomfort=0.6),
    )
    first = EmotionHistoryEntry(
        source_event_id="first-contact",
        before=asdict(neutral),
        after=asdict(affectionate),
        reason="contact_affection_received",
        recorded_at=occurred_at,
        deltas={"joy": 0.035},
    )
    later = EmotionHistoryEntry(
        source_event_id="later-contact",
        before=asdict(affectionate),
        after=asdict(angry),
        reason="contact_boundary_ignored",
        recorded_at=occurred_at + timedelta(seconds=2),
        deltas={"anger": 0.4, "discomfort": 0.6},
    )

    context = EmotionContextBuilder().build_for_event(
        angry,
        (first, later),
        source_event_id="first-contact",
        now=occurred_at,
    )

    assert context.current["valence"] == pytest.approx(0.04)
    assert context.current["reactive"]["joy"] == pytest.approx(0.035)
    assert context.current["reactive"]["anger"] == 0.0
    assert len(context.recent_history) == 1


def test_agent_life_service_applies_event_appraisal_and_elapsed_decay() -> None:
    started_at = datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)
    service = AgentLifeService(ActivityManager(), now=started_at)
    event = AgentEvent(
        event_type=AgentEventType.ACTION_FAILED,
        occurred_at=started_at,
    )

    after_event = service.handle_event(event).current_emotion
    service.plan_next_event(now=started_at + timedelta(minutes=30))
    after_decay = service.agent_state.current_emotion

    assert after_event.arousal == pytest.approx(0.58)
    assert after_event.valence == pytest.approx(-0.08)
    assert after_event.talkativeness == pytest.approx(0.48)
    assert after_decay.arousal == pytest.approx(0.5)
    assert after_decay.valence == pytest.approx(0.0)
    assert after_decay.talkativeness == pytest.approx(0.5)
    assert after_decay.reactive.sadness == pytest.approx(0.02)
    assert after_decay.reactive.emotional_pressure == pytest.approx(0.0133333333)


def test_emotion_state_updater_keeps_mixed_emotions_and_derives_angry_mood() -> None:
    updated = EmotionStateUpdater().apply(
        EmotionState(),
        EmotionAppraisal(
            anger_delta=0.65,
            sadness_delta=0.35,
            discomfort_delta=0.4,
            pressure_delta=0.3,
            arousal_delta=0.25,
            valence_delta=-0.45,
            talkativeness_delta=-0.1,
            reason="trusted_person_hurtful_statement",
        ),
    )

    assert updated.mood == MoodType.ANGRY
    assert updated.reactive.anger == pytest.approx(0.65)
    assert updated.reactive.sadness == pytest.approx(0.35)
    assert updated.reactive.discomfort == pytest.approx(0.4)
    assert updated.reactive.emotional_pressure == pytest.approx(0.3)


def test_emotion_state_updater_derives_sad_mood_from_loss_appraisal() -> None:
    updated = EmotionStateUpdater().apply(
        EmotionState(),
        EmotionAppraisal(
            sadness_delta=0.7,
            surprise_delta=0.2,
            arousal_delta=-0.1,
            valence_delta=-0.5,
            talkativeness_delta=-0.25,
            reason="loss_received",
        ),
    )

    assert updated.mood == MoodType.SAD
    assert updated.reactive.sadness == pytest.approx(0.7)
    assert updated.talkativeness == pytest.approx(0.25)


def test_emotion_state_updater_decays_surprise_faster_than_sadness() -> None:
    state = EmotionState(
        mood=MoodType.SAD,
        reactive=ReactiveEmotionState(
            sadness=0.8,
            surprise=0.8,
        ),
    )

    decayed = EmotionStateUpdater().decay(state, elapsed_seconds=300.0)

    assert decayed.reactive.surprise == 0.0
    assert decayed.reactive.sadness == pytest.approx(0.8 * (1.0 - (300.0 / 3600.0)))
    assert decayed.mood == MoodType.SAD
