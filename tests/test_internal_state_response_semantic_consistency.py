from __future__ import annotations

import json

from app.adapters.prompt.directive_aware_prompt_builders import (
    CharacterPromptBuilder,
    ResponseValidatorPromptBuilder,
)
from app.domain.character_response import (
    ActivityExecutionStatus,
    CharacterResponse,
    ResponseClaim,
    ResponseContext,
)
from app.domain.cognitive_direction import (
    ExpectedResponse,
    InputSpeechAct,
    InputTarget,
    InternalDirective,
    ResponseMode,
    StructuredInputMeaning,
    ValidatedActionPlan,
)
from app.runtime.character_response_pipeline import CharacterResponsePipeline
from app.runtime.separated_situation_evaluator import (
    SeparatedSituationEvaluationAdapter,
)


def _meaning(
    *,
    target_type: str = "internal_state",
    target_id: str = "joy",
) -> StructuredInputMeaning:
    return StructuredInputMeaning(
        input_speech_act=InputSpeechAct.QUESTION,
        primary_intent="ask_internal_state",
        expected_response=ExpectedResponse.DIRECT_ANSWER,
        target=InputTarget(target_type, target_id),
        confidence=0.99,
    )


def _directive() -> InternalDirective:
    return InternalDirective(
        response_mode=ResponseMode.ANSWER,
        response_goal=(
            "ユーザーが尋ねた内的状態について、現在の状態に沿って自然に直接答える"
        ),
        activity_intent=None,
        initiative_level=0.2,
        question_budget=0,
        new_direction_budget=0,
        self_disclosure_level=0.35,
        forbidden_claims=(
            "engagementやcuriosityを、質問対象の内的状態と同一概念として扱う",
        ),
    )


def _envelope(
    *,
    target_type: str = "internal_state",
    target_id: str = "joy",
) -> dict[str, object]:
    return ValidatedActionPlan(
        meaning=_meaning(target_type=target_type, target_id=target_id),
        directive=_directive(),
    ).as_context()


def _context(
    *,
    target_type: str = "internal_state",
    target_id: str = "joy",
    avoid_repetition: bool = True,
) -> ResponseContext:
    constraints: dict[str, object] = {
        "_internal_directive": _envelope(
            target_type=target_type,
            target_id=target_id,
        )
    }
    if avoid_repetition:
        constraints["avoid_repetition"] = True
    return ResponseContext(
        user_input="楽しい？",
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.WAITING_INPUT,
        failure_reason=None,
        result_summary="",
        allowed_claims=(ResponseClaim.CONVERSATION_ONLY,),
        forbidden_claims=(),
        activity_goal="現在の内部状態へ直接答える",
        speech_act="question",
        emotion={
            "current": {
                "reactive": {
                    "joy": 0.0,
                    "amusement": 0.0,
                    "calm": 0.58,
                }
            }
        },
        drive={
            "curiosity": 0.61,
            "engagement": 0.57,
        },
        constraints=constraints,
        recent_speech_summary="- 今はわりと楽しい気分だよ。",
    )


def test_internal_state_direct_question_enables_existing_repetition_detector() -> None:
    payload = SeparatedSituationEvaluationAdapter._legacy_situation_payload(
        ValidatedActionPlan(
            meaning=_meaning(),
            directive=_directive(),
        )
    )

    constraints = payload["constraints"]
    assert isinstance(constraints, dict)
    assert constraints["avoid_repetition"] is True
    assert "_internal_directive" in constraints


def test_non_internal_state_question_does_not_force_repetition_detector() -> None:
    payload = SeparatedSituationEvaluationAdapter._legacy_situation_payload(
        ValidatedActionPlan(
            meaning=_meaning(target_type="topic", target_id="ocean"),
            directive=_directive(),
        )
    )

    constraints = payload["constraints"]
    assert isinstance(constraints, dict)
    assert "avoid_repetition" not in constraints


def test_existing_repetition_detector_rejects_same_internal_state_answer() -> None:
    context = _context()

    assert CharacterResponsePipeline._is_recent_speech_duplicate(
        "今はわりと楽しい気分だよ。",
        context,
    )


def test_character_prompt_exposes_typed_target_and_current_state_as_one_contract() -> None:
    prompt = CharacterPromptBuilder().build(
        _context(),
        character_profile=None,
        correction=None,
    )

    assert "# Direct Internal State Answer Contract" in prompt
    assert '"id": "joy"' in prompt
    assert '"joy": 0.0' in prompt
    assert '"amusement": 0.0' in prompt
    assert '"curiosity": 0.61' in prompt
    assert "current structured state" in prompt
    assert "curiosityやengagementはjoy/amusementではなく" in prompt
    assert "現在状態の事実を上書きしない" in prompt


def test_validator_prompt_rejects_cross_state_substitution_semantically() -> None:
    prompt = ResponseValidatorPromptBuilder().build(
        _context(),
        CharacterResponse(
            speech="なんだか色々気になってて、今は楽しい気分だよ。",
            claims=(ResponseClaim.CONVERSATION_ONLY,),
        ),
    )

    assert "# Direct Internal State Semantic Validation" in prompt
    assert '"id": "joy"' in prompt
    assert '"joy": 0.0' in prompt
    assert '"curiosity": 0.61' in prompt
    assert "別の内部状態の高さをtarget自身の高さ・存在へ代用" in prompt
    assert "curiosity/engagementをjoy/amusementとして扱わない" in prompt
    assert "accepted=false" in prompt
    assert "文字列照合ではなく意味関係の検証" in prompt


def test_repetition_correction_preserves_same_internal_state_target() -> None:
    correction = json.dumps(
        {
            "reason": "recent_speech_too_similar",
            "claim_differences": ["semantic_novelty_required"],
            "instruction": "直近発話とは異なる主題または内容を選ぶ",
        },
        ensure_ascii=False,
    )

    prompt = CharacterPromptBuilder().build(
        _context(),
        character_profile=None,
        correction=correction,
    )

    assert "# Internal State Repetition Correction" in prompt
    assert "別話題へ移る意味ではない" in prompt
    assert "同じtyped internal-state targetへ直接答え続け" in prompt
    assert "current structured stateから改めて自然に表現" in prompt
    assert "無関係な新話題へ" in prompt


def test_non_internal_state_target_does_not_get_internal_state_contract() -> None:
    prompt = CharacterPromptBuilder().build(
        _context(target_type="topic", target_id="ocean"),
        character_profile=None,
        correction=None,
    )

    assert "# Direct Internal State Answer Contract" not in prompt
