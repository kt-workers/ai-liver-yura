from app.adapters.prompt import SituationEvaluatorPromptBuilder
from app.domain.behavior import BehaviorPlanningContext


def test_prompt_requires_conversation_sentinel_for_ordinary_conversation() -> None:
    prompt = SituationEvaluatorPromptBuilder().build(
        BehaviorPlanningContext(
            user_text="今日は何するの？",
            source_event_id="event-1",
            available_capabilities=frozenset(),
        )
    )

    assert "activity_typeをconversation" in prompt
    assert "operationをdiscussまたはexplain" in prompt
    assert "conversation_with_userはRuntime内部のActivity名" in prompt
    assert "Situation Evaluatorの出力には使用しない" in prompt
    assert "available_activitiesが空" in prompt
    assert '"activity_type": "conversation|available_activities[].activity_type|null"' in prompt
