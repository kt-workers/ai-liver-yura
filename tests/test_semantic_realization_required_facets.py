from __future__ import annotations

from app.adapters.prompt.character_realization_validator_prompt_builder import (
    CharacterRealizationValidatorPromptBuilder,
)
from app.domain.character_response import (
    ActivityExecutionStatus,
    CharacterResponse,
    ResponseClaim,
    ResponseContext,
)
from app.domain.character_utterance import LinguisticPerformance
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
        memory={
            "semantic_utterance_plan": plan.as_context(),
            "semantic_validation": {
                "accepted": True,
                "reason": "semantic_plan_consistent",
                "differences": [],
            },
        },
    )


def _response() -> CharacterResponse:
    return CharacterResponse(
        speech="うん、少しあるよ。",
        expression="neutral",
        claims=(ResponseClaim.CONVERSATION_ONLY,),
        linguistic_performance=LinguisticPerformance(
            phrasing=("うん", "少しあるよ"),
            emphasis=("少し",),
            delivery_tags=("gentle",),
        ),
        semantic_realizations=("proposition:0:current_desire",),
    )


def test_validator_marks_primary_predicate_state_certainty_and_non_null_concept_as_required_facets() -> None:
    prompt = CharacterRealizationValidatorPromptBuilder().build(
        _context(),
        _response(),
    )

    assert '"required": true' in prompt
    assert '"required_facets": ["predicate", "state", "certainty", "concept"]' in prompt
    assert '"if_realized_required_facets": ["predicate", "state", "certainty", "concept"]' in prompt
    assert "predicate_preservedは内部英語ラベルがspeechに存在するかではなく" in prompt
    assert "conceptを落として単なる『何かある』等の存在表明だけに縮退した場合はreject" in prompt
    assert "state=presentは存在のみで強度を含まない" in prompt
    assert "『少し』『かなり』等の強度を追加した場合はreject" in prompt
    assert "medium/lowを強度へ変換せず" in prompt
    assert "response_content_plan.primary_desire" not in prompt


def test_semantic_realization_id_requires_per_proposition_facet_validation() -> None:
    prompt = CharacterRealizationValidatorPromptBuilder().build(
        _context(),
        _response(),
    )

    assert '"semantic_realizations": ["proposition:0:current_desire"]' in prompt
    assert "IDがあるだけで意味整合を自動承認せず" in prompt
    assert "realized_proposition_checksで個別検証する" in prompt
    assert "各IDについてちょうど1件返す" in prompt
    assert '"state_fidelity":"exact"' in prompt
