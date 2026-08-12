from __future__ import annotations

from app.adapters.prompt.character_language_realizer_prompt_builder import (
    CharacterLanguageRealizerPromptBuilder,
)
from app.domain.character import CharacterProfile
from app.domain.character_response import ActivityExecutionStatus, ResponseClaim, ResponseContext
from app.domain.semantic_utterance import SemanticProposition, SemanticTarget, SemanticUtterancePlan


def _prompt(*, concept: str | None) -> str:
    plan = SemanticUtterancePlan(
        speech_act="direct_answer",
        target=SemanticTarget("internal_state", "current_desire"),
        propositions=(
            SemanticProposition(
                kind="self_state",
                predicate="current_desire",
                state="present",
                certainty="medium",
                concept=concept,
            ),
        ),
        response_length="short",
        question_budget=0,
        new_direction_budget=0,
    )
    context = ResponseContext(
        user_input="何かしたい？",
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.WAITING_INPUT,
        failure_reason=None,
        result_summary="",
        allowed_claims=(ResponseClaim.CONVERSATION_ONLY,),
        forbidden_claims=(),
        activity_goal="現在の欲求へ直接答える",
        memory={"semantic_utterance_plan": plan.as_context()},
    )
    profile = CharacterProfile(
        name="ゆら",
        personality="穏やか",
        speaking_style="自然な日本語",
        streaming_style="自然に反応する",
    )
    return CharacterLanguageRealizerPromptBuilder().build(
        context,
        character_profile=profile,
        correction=None,
    )


def test_predicate_is_required_even_when_concept_exists() -> None:
    prompt = _prompt(concept="curiosity")

    assert '"required_facets": ["predicate", "state", "certainty", "concept"]' in prompt
    assert '"predicate_semantics": "preserve_target_meaning"' in prompt
    assert '"predicate_realization": "semantically_explicit_in_speech"' in prompt
    assert '"concept_role": "modify_predicate_not_replace_it"' in prompt
    assert "conceptだけを述べてpredicateの意味をspeechから消すのは不正" in prompt


def test_predicate_remains_required_when_concept_is_null() -> None:
    prompt = _prompt(concept=None)

    assert '"required_facets": ["predicate", "state", "certainty"]' in prompt
    assert '"predicate_semantics": "preserve_target_meaning"' in prompt
    assert '"concept_role": "none"' in prompt
