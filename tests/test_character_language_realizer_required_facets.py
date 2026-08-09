from __future__ import annotations

from app.adapters.prompt.character_language_realizer_prompt_builder import (
    CharacterLanguageRealizerPromptBuilder,
)
from app.domain.character import CharacterProfile
from app.domain.character_response import (
    ActivityExecutionStatus,
    ResponseClaim,
    ResponseContext,
)
from app.domain.semantic_utterance import (
    SemanticProposition,
    SemanticTarget,
    SemanticUtterancePlan,
)


def _context() -> ResponseContext:
    plan = SemanticUtterancePlan(
        speech_act="direct_answer",
        target=SemanticTarget("internal_state", "current_desire"),
        propositions=(
            SemanticProposition(
                kind="self_state",
                predicate="current_desire",
                state="present",
                certainty="medium",
                concept="curiosity",
                evidence_refs=("response_content_plan.primary_desire",),
            ),
        ),
        response_length="short",
        self_disclosure="brief",
        question_budget=0,
        new_direction_budget=0,
    )
    return ResponseContext(
        user_input="何かしたい？",
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.WAITING_INPUT,
        failure_reason=None,
        result_summary="",
        allowed_claims=(ResponseClaim.CONVERSATION_ONLY,),
        forbidden_claims=(),
        activity_goal="現在の欲求へ直接答える",
        speech_act="question",
        memory={"semantic_utterance_plan": plan.as_context()},
    )


def _profile() -> CharacterProfile:
    return CharacterProfile(
        name="ゆら",
        personality="穏やか",
        speaking_style="自然な日本語",
        streaming_style="会話相手へ自然に反応する",
    )


def test_primary_non_null_concept_is_declared_as_required_semantic_facet() -> None:
    prompt = CharacterLanguageRealizerPromptBuilder().build(
        _context(),
        character_profile=_profile(),
        correction=None,
    )

    assert '"state": "present"' in prompt
    assert '"certainty": "medium"' in prompt
    assert '"concept": "curiosity"' in prompt
    assert '"required": true' in prompt
    assert '"required_facets": ["state", "certainty", "concept"]' in prompt
    assert "単なる『何かある』等の存在表明だけへ縮退しない" in prompt
    assert "primary propositionのIDを列挙する場合はrequired_facetsをすべて保持" in prompt
    assert "response_content_plan.primary_desire" not in prompt


def test_present_state_does_not_license_new_intensity_and_certainty_stays_epistemic() -> None:
    prompt = CharacterLanguageRealizerPromptBuilder().build(
        _context(),
        character_profile=_profile(),
        correction=None,
    )

    assert "state=presentは存在を表すだけで強度を含まない" in prompt
    assert "『少し』『かなり』等の強度を新しく推測・追加しない" in prompt
    assert "speechの程度・強弱表現を内部点検" in prompt
    assert "対応する強度stateがない対象へ付いた程度表現は除去" in prompt
    assert "medium/lowのcertainty" in prompt
    assert "強度表現へ置き換えない" in prompt
