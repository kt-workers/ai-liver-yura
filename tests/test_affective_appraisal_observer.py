from __future__ import annotations

from datetime import datetime, timezone
from typing import cast

import pytest

from app.domain.emotions import (
    AffectiveAppraisalComparison,
    AffectiveAppraisalDimensions,
    EmotionAppraisal,
    EmotionCause,
    EmotionState,
)
from app.domain.events import AgentEvent, AgentEventType
from app.domain.relationships import RelationshipState
from app.runtime.affective_appraisal_observer import AffectiveAppraisalObserver
from app.runtime.agent_event_state_updater import AgentEventStateUpdater
from app.runtime.agent_state import AgentState
from app.runtime.emotion_appraiser import EmotionAppraiser
from app.runtime.emotion_state_updater import EmotionStateUpdater
from app.shared.contracts.memory import EmotionHistoryRecord
from app.utils.trace import TraceLogger


class _RecordingTraceLogger:
    def __init__(self) -> None:
        self.records: list[tuple[str, dict[str, object]]] = []

    def info(self, label: str, **values: object) -> None:
        self.records.append((label, values))


def test_observer_builds_typed_evidence_without_logging_raw_input() -> None:
    before = EmotionState()
    legacy = EmotionAppraisal(
        joy_delta=0.12,
        surprise_delta=0.08,
        arousal_delta=0.10,
        valence_delta=0.15,
        reason="interesting_user_input",
        cause=EmotionCause(
            category="interesting_user_input",
            summary="興味深い入力を受け取った",
            target="deep_sea_pressure_adaptation",
        ),
        confidence=0.84,
    )
    updater = EmotionStateUpdater()
    actual_after = updater.apply(before, legacy)
    relationship = RelationshipState(
        counterpart_id="human-user",
        display_name="人間さん",
        familiarity=0.70,
        trust=0.80,
        affinity=0.60,
        interaction_count=12,
    )
    history = (
        EmotionHistoryRecord(
            source_event_id="previous-event",
            before={},
            after={},
            reason="interesting_user_input",
            cause_category="interesting_user_input",
            recorded_at=datetime(2026, 8, 6, tzinfo=timezone.utc),
        ),
    )
    event = AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={
            "text": "この本文はTraceへ複製しない",
            "structured_input_meaning": {
                "input_speech_act": "statement",
                "primary_intent": "provide_information",
                "expected_response": "acknowledgement",
                "target": {
                    "type": "topic",
                    "id": "deep_sea_pressure_adaptation",
                },
                "confidence": 0.91,
            },
        },
    )
    trace = _RecordingTraceLogger()
    observer = AffectiveAppraisalObserver(
        emotion_state_updater=updater,
        trace_logger=cast(TraceLogger, trace),
    )

    appraisal, comparison = observer.observe(
        event,
        legacy_appraisal=legacy,
        before_emotion=before,
        actual_after_emotion=actual_after,
        relationship=relationship,
        recent_history=history,
    )

    assert appraisal.meaning.available is True
    assert appraisal.meaning.input_speech_act == "statement"
    assert appraisal.meaning.primary_intent == "provide_information"
    assert appraisal.meaning.target_id == "deep_sea_pressure_adaptation"
    assert appraisal.confidence == 0.91
    assert appraisal.relationship_counterpart_id == "human-user"
    assert appraisal.recent_emotion_history_count == 1
    assert appraisal.similar_cause_count == 1
    assert appraisal.dimensions.social_relevance == 1.0
    assert appraisal.dimensions.relationship_significance > 0.0
    assert comparison.matched is True
    assert comparison.max_abs_difference == 0.0

    label, values = trace.records[-1]
    assert label == "affective_appraisal:shadow_compared"
    assert values["meaning_available"] is True
    assert values["comparison_matched"] is True
    assert "text" not in values
    assert "この本文はTraceへ複製しない" not in repr(values)


def test_observer_accepts_nested_validated_meaning_context() -> None:
    before = EmotionState()
    legacy = EmotionAppraisal(source_event_id="source-event")
    event = AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={
            "_internal_directive": {
                "structured_input_meaning": {
                    "input_speech_act": "question",
                    "primary_intent": "ask_current_feeling",
                    "expected_response": "direct_answer",
                    "target": {"type": "state", "id": "current_emotion"},
                    "confidence": 0.77,
                }
            }
        },
    )
    after = EmotionStateUpdater().apply(before, legacy)

    appraisal, comparison = AffectiveAppraisalObserver().observe(
        event,
        legacy_appraisal=legacy,
        before_emotion=before,
        actual_after_emotion=after,
        relationship=None,
    )

    assert appraisal.meaning.available is True
    assert appraisal.meaning.source.endswith(
        "_internal_directive.structured_input_meaning"
    )
    assert appraisal.meaning.input_speech_act == "question"
    assert appraisal.meaning.target_type == "state"
    assert comparison.matched is True


def test_observer_marks_meaning_unavailable_without_reinterpreting_raw_text() -> None:
    before = EmotionState()
    legacy = EmotionAppraisal(arousal_delta=0.02, reason="user_attention_received")
    event = AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"text": "意味解析前の入力"},
    )
    after = EmotionStateUpdater().apply(before, legacy)

    appraisal, comparison = AffectiveAppraisalObserver().observe(
        event,
        legacy_appraisal=legacy,
        before_emotion=before,
        actual_after_emotion=after,
        relationship=None,
    )

    assert appraisal.meaning.available is False
    assert appraisal.meaning.source == "unavailable"
    assert appraisal.meaning.primary_intent is None
    assert "意味解析前の入力" not in repr(appraisal.as_context())
    assert comparison.matched is True


def test_comparison_reports_shadow_projection_difference() -> None:
    projected = EmotionState(arousal=0.80, valence=0.40, talkativeness=0.70)
    actual = EmotionState(arousal=0.50, valence=0.00, talkativeness=0.50)

    comparison = AffectiveAppraisalComparison.compare(projected, actual)

    assert comparison.matched is False
    assert comparison.max_abs_difference == pytest.approx(0.40)
    assert set(comparison.mismatched_fields) == {
        "arousal",
        "valence",
        "talkativeness",
    }


def test_dimensions_clamp_observation_values_to_contract_ranges() -> None:
    dimensions = AffectiveAppraisalDimensions(
        pleasantness=2.0,
        activation=-1.0,
        novelty=1.5,
        social_relevance=-0.5,
        relationship_significance=1.2,
        certainty=4.0,
        controllability=-3.0,
        approach=-2.0,
        tension=2.0,
    )

    assert dimensions.pleasantness == 1.0
    assert dimensions.activation == 0.0
    assert dimensions.novelty == 1.0
    assert dimensions.social_relevance == 0.0
    assert dimensions.relationship_significance == 1.0
    assert dimensions.certainty == 1.0
    assert dimensions.controllability == 0.0
    assert dimensions.approach == -1.0
    assert dimensions.tension == 1.0


def test_agent_event_state_update_keeps_legacy_emotion_as_source_of_truth() -> None:
    event = AgentEvent(
        event_type=AgentEventType.ACTION_FAILED,
        payload={"reason": "phase1_observation_test"},
    )
    before = AgentState()
    legacy_appraisal = EmotionAppraiser().appraise(
        event,
        current_emotion=before.current_emotion,
        relationship=None,
        recent_history=(),
    )
    expected_after = EmotionStateUpdater().apply(
        before.current_emotion,
        legacy_appraisal,
    )

    result = AgentEventStateUpdater().update(before, event)

    assert result.after_emotion == expected_after
    assert result.state.current_emotion == expected_after
    assert result.affective_appraisal.projection_source == (
        "legacy_emotion_appraiser_shadow"
    )
    assert result.affective_comparison.matched is True
