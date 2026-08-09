from __future__ import annotations

import json

from app.domain.activities import Activity, ActivityType
from app.domain.character_response import (
    ActivityExecutionResult,
    ActivityExecutionStatus,
    ResponseClaim,
    ResponseContext,
)
from app.domain.semantic_utterance import SemanticUtterancePlan
from app.runtime.internal_state_response_context import InternalStateAwareResponseContextBuilder
from app.runtime.response_semantics_planner import ResponseSemanticsPlanner


def _envelope(target_id: str) -> dict[str, object]:
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
            "content_requirements": ["内部状態の説明文を固定しない"],
            "forbidden_claims": [],
        },
    }


def _context(
    target_id: str = "joy",
    *,
    memory: dict[str, object] | None = None,
    relationship: dict[str, object] | None = None,
) -> ResponseContext:
    return ResponseContext(
        user_input="楽しい？",
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.WAITING_INPUT,
        failure_reason=None,
        result_summary="",
        allowed_claims=(ResponseClaim.CONVERSATION_ONLY,),
        forbidden_claims=(),
        activity_goal="質問へ直接答える",
        speech_act="question",
        emotion={
            "current": {
                "reactive": {
                    "joy": 0.0,
                    "amusement": 0.0,
                    "calm": 0.58,
                    "anger": 0.0,
                }
            }
        },
        drive={"curiosity": 0.82, "engagement": 0.78, "energy": 0.7},
        relationship=relationship or {},
        memory=memory or {},
        constraints={"_internal_directive": _envelope(target_id)},
    )


def test_zero_joy_becomes_absent_semantic_proposition() -> None:
    plan = ResponseSemanticsPlanner().plan(_context("joy"))

    assert plan.speech_act == "direct_answer"
    assert plan.target is not None
    assert plan.target.id == "joy"
    assert len(plan.propositions) == 1
    proposition = plan.propositions[0]
    assert proposition.predicate == "joy"
    assert proposition.state == "absent"
    assert proposition.evidence_refs == ("emotion.current.reactive.joy",)
    assert "substitute_non_target_state" in plan.forbidden_additions


def test_high_curiosity_is_not_promoted_into_joy_meaning() -> None:
    plan = ResponseSemanticsPlanner().plan(_context("joy"))
    serialized = json.dumps(plan.as_context(), ensure_ascii=False)

    assert "curiosity" not in serialized
    assert "0.82" not in serialized
    assert '"state": "absent"' in serialized


def test_current_feeling_uses_emotion_overview_without_raw_values() -> None:
    plan = ResponseSemanticsPlanner().plan(_context("current_feeling"))

    proposition = plan.propositions[0]
    assert proposition.predicate == "current_feeling"
    assert proposition.state == "overview"
    assert proposition.evidence_refs == ("emotion",)
    serialized = json.dumps(plan.as_context(), ensure_ascii=False)
    assert "0.58" not in serialized


def test_current_desire_uses_existing_semantic_desire_concept() -> None:
    plan = ResponseSemanticsPlanner().plan(
        _context(
            "current_desire",
            memory={
                "response_content_plan": {
                    "primary_desire": "connection",
                    "self_disclosure_level": "brief",
                    "question_budget": 0,
                    "new_direction_budget": 0,
                    "observation_only": True,
                }
            },
        )
    )

    proposition = plan.propositions[0]
    assert proposition.predicate == "current_desire"
    assert proposition.state == "present"
    assert proposition.concept == "connection"
    assert proposition.evidence_refs == ("response_content_plan.primary_desire",)


def test_directive_budget_and_relationship_content_facets_are_preserved() -> None:
    plan = ResponseSemanticsPlanner().plan(
        _context(
            "anger",
            relationship={
                "disclosure_permission": "limited",
                "boundary_sensitivity": "high",
                "social_distance": "close",
                "current_tension": "low",
                "trust": 0.92,
            },
        )
    )

    assert plan.question_budget == 0
    assert plan.new_direction_budget == 0
    assert plan.self_disclosure == "brief"
    assert plan.interpersonal.disclosure_permission == "limited"
    assert plan.interpersonal.boundary_sensitivity == "high"
    assert plan.interpersonal.social_distance == "close"
    assert plan.interpersonal.current_tension == "low"
    assert "0.92" not in json.dumps(plan.as_context(), ensure_ascii=False)


def test_semantic_plan_round_trips_across_response_context_boundary() -> None:
    original = ResponseSemanticsPlanner().plan(_context("joy"))

    restored = SemanticUtterancePlan.from_context(original.as_context())

    assert restored == original


def test_production_response_context_builder_attaches_semantic_plan() -> None:
    result = ActivityExecutionResult(
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.WAITING_INPUT,
        constraints={"_internal_directive": _envelope("joy")},
    )
    activity = Activity(
        activity_type=ActivityType.CONVERSATION,
        goal="現在の内部状態へ自然に直接答える",
        context={
            "activity_execution_result": result,
            "event_payload": {
                "text": "楽しい？",
                "activity_execution_result": result,
            },
            "emotion": {
                "current": {
                    "reactive": {
                        "joy": 0.0,
                        "amusement": 0.0,
                        "calm": 0.58,
                    }
                }
            },
            "drive": {"curiosity": 0.82, "engagement": 0.78},
        },
    )

    context = InternalStateAwareResponseContextBuilder().build(activity)
    restored = SemanticUtterancePlan.from_context(
        context.memory.get("semantic_utterance_plan")
    )

    assert restored is not None
    assert restored.target is not None
    assert restored.target.id == "joy"
    assert restored.propositions[0].state == "absent"
