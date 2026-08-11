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
                concept="connection",
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
        constraints={"_internal_directive": {"existence_boundaries": []}},
    )


def _prompt(speech: str = "つながりたい気持ちは、あると思うよ。") -> str:
    return CharacterRealizationValidatorPromptBuilder().build(
        _context(),
        CharacterResponse(
            speech=speech,
            semantic_realizations=("proposition:0:current_desire",),
        ),
    )


def test_primary_predicate_must_be_grounded_in_speech_without_context_completion() -> None:
    prompt = _prompt("今はかなり強いよ。")

    assert "User Wording Hintによる省略補完をしない" in prompt
    assert "対象省略だけなら" in prompt
    assert "predicate_preserved=false" in prompt
    assert "predicate_evidence_spans" in prompt
    assert "対象を識別しない語だけをpredicate evidenceにしない" in prompt
    assert '"predicate_context_dependency": "forbidden"' in prompt


def test_medium_certainty_and_non_null_concept_require_surface_evidence() -> None:
    prompt = _prompt()

    assert "certainty_evidence_spans" in prompt
    assert "medium/lowなのに無標の断定だけならcertainty_preserved=false" in prompt
    assert "concept_evidence_spans" in prompt
    assert "concept=nullならconcept_evidence_spans=[]" in prompt
    assert '"certainty_surface_requirement": "overt_epistemic_modality"' in prompt


def test_intensity_evidence_distinguishes_degree_from_bare_presence() -> None:
    prompt = _prompt()

    assert "『低め』『強め』等のdegreeを担う表現は根拠になり得る" in prompt
    assert "bare presenceだけではlow/moderate/highの" in prompt
    assert "intensity_evidence_spans" in prompt


def test_free_text_differences_must_match_structured_checks() -> None:
    prompt = _prompt()

    assert "accepted/reason/differencesとrealized_proposition_checksを自己矛盾させない" in prompt
    assert "対応checkもその不一致を表す" in prompt
    assert "構造checkがexactでevidenceも成立するfacet" in prompt
