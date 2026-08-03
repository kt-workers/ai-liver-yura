from __future__ import annotations

import json

import pytest

from app.domain.activities import Activity
from app.domain.behavior import BehaviorPlanningContext
from app.ports.llm_roles import ResponseGeneratorRoleAdapter
from app.runtime.situation_evaluator import SituationEvaluator


class StubResponseGenerator:
    async def generate_response(self, activity: Activity) -> str:
        return json.dumps(
            {
                "decision": "continue_conversation",
                "activity_type": "conversation_with_user",
                "operation": "continue",
                "goal": "ユーザーとの通常会話を続ける",
                "constraints": {},
                "speech_act": "statement",
                "conversation_phase": "active",
                "initiative_level": 0.25,
                "negated": False,
                "hypothetical": False,
                "past_reference": False,
                "knowledge_question": False,
                "confidence": 0.94,
                "reason": "ordinary_conversation",
                "ongoing_input_decision": None,
                "semantic_equivalence": {
                    "candidate_group": [],
                    "intent": "unknown",
                    "operation": "unknown",
                    "goal": "unknown",
                    "reasons": ["candidate_group_is_empty"],
                },
            },
            ensure_ascii=False,
        )


class StubPromptBuilder:
    def build(self, context: BehaviorPlanningContext) -> str:
        return "evaluate"


@pytest.mark.asyncio
async def test_runtime_conversation_alias_is_adopted_without_fallback() -> None:
    evaluator = SituationEvaluator(
        ResponseGeneratorRoleAdapter(StubResponseGenerator()),
        prompt_builder=StubPromptBuilder(),
    )
    context = BehaviorPlanningContext(
        user_text="ふむふむ",
        source_event_id="runtime-regression-event",
        available_capabilities=frozenset(),
        activity_definitions=(),
    )

    analysis = await evaluator.evaluate(context)

    assert analysis.evaluator_type == "llm"
    assert analysis.activity_candidate is None
    assert analysis.operation is not None
    assert analysis.operation.value == "discuss"
    assert analysis.reason == "ordinary_conversation"
    assert analysis.confidence == pytest.approx(0.94)
