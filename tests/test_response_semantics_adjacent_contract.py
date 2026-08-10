from __future__ import annotations

import json

from app.domain.activities import Activity, ActivityType
from app.domain.character_response import ActivityExecutionResult, ActivityExecutionStatus
from app.domain.semantic_utterance import SemanticUtterancePlan
from app.runtime.internal_state_response_context import InternalStateAwareResponseContextBuilder


def _envelope(target_id: str = "joy") -> dict[str, object]:
    return {
        "structured_input_meaning": {
            "input_speech_act": "question",
            "primary_intent": "ask_internal_state",
            "expected_response": "direct_answer",
            "target": {"type": "internal_state", "id": target_id},
        },
        "internal_directive": {
            "response_mode": "answer",
            "response_goal": "現在の内部状態へ自然に直接答える",
            "question_budget": 0,
            "new_direction_budget": 0,
            "self_disclosure_level": 0.35,
            "content_requirements": [],
            "forbidden_claims": [],
        },
    }


def _activity(
    *,
    target_id: str = "joy",
    event_emotion: object | None = None,
    activity_emotion: object | None = None,
    autonomous_emotion: object | None = None,
    event_drive: object | None = None,
    activity_drive: object | None = None,
    autonomous_drive: object | None = None,
    memory: dict[str, object] | None = None,
    relationship: dict[str, object] | None = None,
    recent_speech_summary: str = "",
    directive: object | None = None,
    avoid_repetition: bool = False,
    user_text: str = "楽しい？",
) -> Activity:
    constraints: dict[str, object] = {
        "_internal_directive": _envelope(target_id) if directive is None else directive,
    }
    if avoid_repetition:
        constraints["avoid_repetition"] = True

    result = ActivityExecutionResult(
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.WAITING_INPUT,
        constraints=constraints,
    )

    event_payload: dict[str, object] = {
        "text": user_text,
        "activity_execution_result": result,
    }
    if event_emotion is not None:
        event_payload["emotion"] = event_emotion
    if event_drive is not None:
        event_payload["drive"] = event_drive
    if memory is not None:
        event_payload["memory"] = memory
    if relationship is not None:
        event_payload["relationship"] = relationship

    autonomous_context: dict[str, object] = {}
    if autonomous_emotion is not None:
        autonomous_context["emotion_state"] = autonomous_emotion
    if autonomous_drive is not None:
        autonomous_context["drive_state"] = autonomous_drive
    if recent_speech_summary:
        autonomous_context["recent_speech_summary"] = recent_speech_summary
    if autonomous_context:
        event_payload["autonomous_situation_context"] = autonomous_context

    activity_context: dict[str, object] = {
        "activity_execution_result": result,
        "event_payload": event_payload,
    }
    if activity_emotion is not None:
        activity_context["emotion"] = activity_emotion
    if activity_drive is not None:
        activity_context["drive"] = activity_drive

    return Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="質問へ直接答える",
        context=activity_context,
    )


def _reactive_joy(value: float) -> dict[str, object]:
    return {"current": {"reactive": {"joy": value}}}


def _restored_plan(activity: Activity) -> tuple[object, SemanticUtterancePlan]:
    context = InternalStateAwareResponseContextBuilder().build(activity)
    plan = SemanticUtterancePlan.from_context(
        context.memory.get("semantic_utterance_plan")
    )
    assert plan is not None
    return context, plan


def test_builder_prefers_event_payload_emotion_over_other_sources() -> None:
    context, plan = _restored_plan(
        _activity(
            event_emotion=_reactive_joy(0.9),
            activity_emotion=_reactive_joy(0.2),
            autonomous_emotion=_reactive_joy(0.4),
        )
    )

    assert context.emotion == _reactive_joy(0.9)
    assert plan.propositions[0].predicate == "joy"
    assert plan.propositions[0].state == "very_high"


def test_builder_falls_back_from_activity_emotion_to_autonomous_emotion() -> None:
    activity_context, activity_plan = _restored_plan(
        _activity(
            activity_emotion=_reactive_joy(0.4),
            autonomous_emotion=_reactive_joy(0.9),
        )
    )
    autonomous_context, autonomous_plan = _restored_plan(
        _activity(autonomous_emotion=_reactive_joy(0.9))
    )

    assert activity_context.emotion == _reactive_joy(0.4)
    assert activity_plan.propositions[0].state == "moderate"
    assert autonomous_context.emotion == _reactive_joy(0.9)
    assert autonomous_plan.propositions[0].state == "very_high"


def test_builder_filters_drive_to_numeric_non_boolean_values() -> None:
    context, plan = _restored_plan(
        _activity(
            target_id="curiosity",
            event_drive={
                "curiosity": 0.82,
                "enabled": True,
                "label": "high",
                "nested": {"energy": 0.7},
            },
        )
    )

    assert context.drive == {"curiosity": 0.82}
    assert plan.propositions[0].predicate == "curiosity"
    assert plan.propositions[0].state == "high"
    serialized = json.dumps(plan.as_context(), ensure_ascii=False)
    assert "0.82" not in serialized
    assert '"enabled"' not in serialized
    assert '"nested"' not in serialized


def test_invalid_directive_does_not_invent_internal_state_semantics() -> None:
    context, plan = _restored_plan(
        _activity(
            event_emotion=_reactive_joy(0.9),
            directive="not-a-directive-envelope",
        )
    )

    assert context.emotion == _reactive_joy(0.9)
    assert plan.target is None
    assert plan.propositions == ()
    assert plan.speech_act == "statement"


def test_builder_preserves_memory_and_semantic_plan_round_trip_contract() -> None:
    raw_user_marker = "RAW-USER-TEXT-MARKER"
    unrelated_memory_marker = "UNRELATED-MEMORY-MARKER"
    context, restored = _restored_plan(
        _activity(
            event_emotion=_reactive_joy(0.0),
            event_drive={"curiosity": 0.82},
            memory={
                "existing_memory": {
                    "marker": unrelated_memory_marker,
                    "value": 42,
                }
            },
            relationship={
                "disclosure_permission": "limited",
                "boundary_sensitivity": "high",
                "social_distance": "close",
                "current_tension": "low",
                "trust": 0.92,
            },
            recent_speech_summary="さっきも同じ話をした",
            avoid_repetition=True,
            user_text=raw_user_marker,
        )
    )

    assert context.memory["existing_memory"] == {
        "marker": unrelated_memory_marker,
        "value": 42,
    }
    serialized = context.memory["semantic_utterance_plan"]
    assert isinstance(serialized, dict)

    assert restored.target is not None
    assert restored.target.type == "internal_state"
    assert restored.target.id == "joy"
    assert restored.propositions[0].state == "absent"
    assert restored.question_budget == 0
    assert restored.new_direction_budget == 0
    assert restored.interpersonal.disclosure_permission == "limited"
    assert restored.interpersonal.boundary_sensitivity == "high"
    assert restored.interpersonal.social_distance == "close"
    assert restored.interpersonal.current_tension == "low"
    assert restored.discourse_context["recent_speech_summary"] == "さっきも同じ話をした"
    assert (
        restored.discourse_context["repetition_policy"]
        == "avoid_semantic_and_phrasal_repeat"
    )

    serialized_text = json.dumps(serialized, ensure_ascii=False)
    assert raw_user_marker not in serialized_text
    assert unrelated_memory_marker not in serialized_text
    assert "0.82" not in serialized_text
    assert "0.92" not in serialized_text


def test_builder_drive_source_precedence_matches_emotion_source_precedence() -> None:
    context, plan = _restored_plan(
        _activity(
            target_id="energy",
            event_drive={"energy": 0.9},
            activity_drive={"energy": 0.2},
            autonomous_drive={"energy": 0.4},
        )
    )

    assert context.drive == {"energy": 0.9}
    assert plan.propositions[0].predicate == "energy"
    assert plan.propositions[0].state == "very_high"
