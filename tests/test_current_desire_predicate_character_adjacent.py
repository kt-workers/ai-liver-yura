from __future__ import annotations

from app.adapters.prompt.character_language_realizer_prompt_builder import (
    CharacterLanguageRealizerPromptBuilder,
)
from app.domain.activities import Activity, ActivityType
from app.domain.character import CharacterProfile
from app.domain.character_response import ActivityExecutionResult, ActivityExecutionStatus
from app.domain.semantic_utterance import SemanticUtterancePlan
from app.runtime.internal_state_response_context import InternalStateAwareResponseContextBuilder


def _profile() -> CharacterProfile:
    return CharacterProfile(
        name="ゆら",
        personality="穏やかで好奇心を持つ",
        speaking_style="やわらかく自然な話し方",
        streaming_style="会話相手へ自然に反応する",
    )


def _context():
    envelope = {
        "structured_input_meaning": {
            "input_speech_act": "question",
            "primary_intent": "ask_internal_state",
            "expected_response": "direct_answer",
            "target": {"type": "internal_state", "id": "current_desire"},
        },
        "internal_directive": {
            "response_mode": "answer",
            "response_goal": "現在の欲求へ自然に直接答える",
            "question_budget": 0,
            "new_direction_budget": 0,
            "self_disclosure_level": 0.35,
            "content_requirements": [],
            "forbidden_claims": [],
        },
    }
    result = ActivityExecutionResult(
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.WAITING_INPUT,
        constraints={"_internal_directive": envelope},
    )
    payload = {
        "text": "何かしたい？",
        "activity_execution_result": result,
        "memory": {
            "response_content_plan": {
                "primary_desire": "curiosity",
                "conversation_strategies": [],
                "value_emphases": [],
                "interpersonal_stance": "balanced",
                "expression_mode": "balanced",
                "self_disclosure_level": "none",
                "conflict_mode": None,
                "question_budget": 1,
                "new_direction_budget": 1,
                "observation_only": True,
                "reasons": ["motivation_projected_to_response_content"],
            }
        },
    }
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="現在の欲求へ直接答える",
        context={
            "activity_execution_result": result,
            "event_payload": payload,
        },
    )
    return InternalStateAwareResponseContextBuilder().build(activity)


def test_current_desire_predicate_survives_planner_to_character_contract() -> None:
    context = _context()
    plan = SemanticUtterancePlan.from_context(
        context.memory.get("semantic_utterance_plan")
    )
    assert plan is not None
    assert plan.propositions[0].predicate == "current_desire"
    assert plan.propositions[0].state == "present"
    assert plan.propositions[0].certainty == "medium"
    assert plan.propositions[0].concept == "curiosity"
    assert plan.propositions[0].evidence_refs == (
        "response_content_plan.primary_desire",
    )

    prompt = CharacterLanguageRealizerPromptBuilder().build(
        context,
        character_profile=_profile(),
        correction=None,
    )

    assert '"predicate": "current_desire"' in prompt
    assert '"required_facets": ["predicate", "state", "certainty", "concept"]' in prompt
    assert '"predicate_semantics": "preserve_target_meaning"' in prompt
    assert '"predicate_realization": "semantically_explicit_in_speech"' in prompt
    assert '"state_semantics": "presence_without_intensity"' in prompt
    assert '"certainty_realization": "epistemic_modality"' in prompt
    assert '"concept_role": "modify_predicate_not_replace_it"' in prompt
    assert '"intensity_allowed": false' in prompt
    assert '"utterance": "何かしたい？"' in prompt
    assert "response_content_plan.primary_desire" not in prompt
    assert "evidence_refs" not in prompt
