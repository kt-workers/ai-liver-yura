from __future__ import annotations

import pytest

from app.adapters.prompt import SituationEvaluatorPromptBuilder
from app.domain.activities import Activity
from app.domain.behavior import BehaviorDecision, BehaviorPlanningContext
from app.runtime.behavior_planner import BehaviorPlanner


class InvalidSituationResponseGenerator:
    async def generate_response(self, activity: Activity) -> str:
        return "{}"


@pytest.mark.asyncio
async def test_conversation_winding_down_does_not_become_unmatched_execution() -> None:
    planner = BehaviorPlanner(
        InvalidSituationResponseGenerator(),
        situation_prompt_builder=SituationEvaluatorPromptBuilder(),
    )
    context = BehaviorPlanningContext(
        user_text="今日はそろそろ終わりにしようか",
        source_event_id="winding-down-event",
        available_capabilities=frozenset(),
    )

    plan = await planner.plan(context)

    assert plan.decision == BehaviorDecision.CONVERSATION
    assert plan.activity_type == "conversation"
    assert plan.reason != "execution_request_without_matching_activity"
    assert "要求された行為を実行したふりをしない" not in plan.planner_constraints
