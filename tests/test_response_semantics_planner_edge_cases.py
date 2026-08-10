from __future__ import annotations

from dataclasses import replace

import pytest

from app.domain.character_response import (
    ActivityExecutionStatus,
    ResponseClaim,
    ResponseContext,
)
from app.domain.semantic_utterance import SemanticUtterancePlan
from app.runtime.response_semantics_planner import ResponseSemanticsPlanner


def _envelope(
    target_id: str,
    *,
    question_budget: object = 0,
    new_direction_budget: object = 0,
) -> dict[str, object]:
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
            "question_budget": question_budget,
            "new_direction_budget": new_direction_budget,
            "self_disclosure_level": 0.35,
            "content_requirements": [],
            "forbidden_claims": [],
        },
    }


def _context(target_id: str = "current_feeling") -> ResponseContext:
    return ResponseContext(
        user_input="今どんな気分？",
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
                    "calm": 0.58,
                }
            }
        },
        drive={},
        relationship={},
        memory={},
        constraints={"_internal_directive": _envelope(target_id)},
    )


def test_current_feeling_without_reactive_emotion_is_unknown_even_if_emotion_exists() -> None:
    context = replace(
        _context(),
        emotion={"current": {"baseline": {"calm": 0.9}}},
    )

    plan = ResponseSemanticsPlanner().plan(context)

    assert len(plan.propositions) == 1
    overview = plan.propositions[0]
    assert overview.predicate == "current_feeling"
    assert overview.state == "unknown"
    assert overview.certainty == "low"
    assert overview.evidence_refs == ()


def test_from_context_does_not_treat_boolean_as_binary_budget() -> None:
    restored = SemanticUtterancePlan.from_context(
        {
            "speech_act": "direct_answer",
            "question_budget": True,
            "new_direction_budget": False,
        }
    )

    assert restored is not None
    assert restored.question_budget == 0
    assert restored.new_direction_budget == 0


def test_typed_plan_rejects_boolean_budget_values() -> None:
    with pytest.raises(ValueError, match="question_budget"):
        SemanticUtterancePlan(speech_act="statement", question_budget=True)

    with pytest.raises(ValueError, match="new_direction_budget"):
        SemanticUtterancePlan(speech_act="statement", new_direction_budget=False)


def test_planner_does_not_treat_boolean_directive_budget_as_integer() -> None:
    context = replace(
        _context("joy"),
        constraints={
            "_internal_directive": _envelope(
                "joy",
                question_budget=True,
                new_direction_budget=False,
            )
        },
    )

    plan = ResponseSemanticsPlanner().plan(context)

    assert plan.question_budget == 0
    assert plan.new_direction_budget == 0
