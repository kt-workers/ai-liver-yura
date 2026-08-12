from app.adapters.prompt.character_realization_observer_prompt_builder import (
    CharacterRealizationObserverPromptBuilder,
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
from app.domain.semantic_validation import RealizedSemanticObservation
from app.runtime.character_realization_validator import CharacterRealizationValidator


def test_observer_contract_and_typed_comparison_reject_unknown_to_guessed_polarity() -> None:
    plan = SemanticUtterancePlan(
        speech_act="direct_answer",
        target=SemanticTarget("internal_state", "current_desire"),
        propositions=(
            SemanticProposition(
                kind="self_state",
                predicate="current_desire",
                state="unknown",
                certainty="low",
            ),
        ),
        response_length="short",
        self_disclosure="brief",
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
    response = CharacterResponse(
        speech="うん、何かしたい気持ちはあるかも。",
        expression="neutral",
        claims=(ResponseClaim.CONVERSATION_ONLY,),
        linguistic_performance=LinguisticPerformance(
            phrasing=("うん", "何かしたい気持ちはあるかも"),
            delivery_tags=("gentle",),
        ),
        semantic_realizations=("proposition:0:current_desire",),
    )

    observer_prompt = CharacterRealizationObserverPromptBuilder().build(
        context,
        response,
        plan,
    )
    assert "unknownは対象の存在・不在・強度・値を現時点で確定していない" in observer_prompt
    assert "特定polarityへcommitしたspeechをunknownにしない" in observer_prompt
    assert "certaintyは対象stateについてのepistemic確かさとして観測する" in observer_prompt

    guessed = RealizedSemanticObservation(
        realization_id="proposition:0:current_desire",
        predicate_realized=True,
        observed_state="present",
        observed_certainty="medium",
        predicate_evidence_spans=("何かしたい気持ち",),
        state_evidence_spans=("あるかも",),
        certainty_evidence_spans=("かも",),
    )
    differences = CharacterRealizationValidator._observation_differences(
        plan,
        response,
        (guessed,),
    )

    assert (
        "proposition:0:current_desire:observed_state_mismatch:"
        "expected=unknown:observed=present"
        in differences
    )
    assert (
        "proposition:0:current_desire:observed_certainty_mismatch:"
        "expected=low:observed=medium"
        in differences
    )
