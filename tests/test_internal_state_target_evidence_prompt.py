from __future__ import annotations

import json

from app.adapters.prompt import CharacterPromptBuilder, ResponseValidatorPromptBuilder
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


def _envelope(target_id: str) -> dict[str, object]:
    meaning = StructuredInputMeaning(
        input_speech_act=InputSpeechAct.QUESTION,
        primary_intent="ask_internal_state",
        expected_response=ExpectedResponse.DIRECT_ANSWER,
        target=InputTarget("internal_state", target_id),
        confidence=0.99,
    )
    directive = InternalDirective(
        response_mode=ResponseMode.ANSWER,
        response_goal="現在の内部状態へ自然に直接答える",
        activity_intent=None,
        initiative_level=0.2,
        question_budget=0,
        new_direction_budget=0,
        self_disclosure_level=0.35,
    )
    return ValidatedActionPlan(meaning=meaning, directive=directive).as_context()


def _context(
    target_id: str = "joy",
    *,
    memory: dict[str, object] | None = None,
) -> ResponseContext:
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
                    "anger": 0.0,
                }
            }
        },
        drive={
            "curiosity": 0.82,
            "engagement": 0.78,
            "energy": 0.7,
        },
        memory=memory or {},
        constraints={
            "avoid_repetition": True,
            "_internal_directive": _envelope(target_id),
        },
    )


def test_character_prompt_prioritizes_exact_target_evidence_over_other_state() -> None:
    prompt = CharacterPromptBuilder().build(
        _context("joy"),
        character_profile=None,
        correction=None,
    )

    assert "# Target-specific Internal State Evidence" in prompt
    assert '"scope": "exact_dimension"' in prompt
    assert '"path": "emotion.current.reactive.joy"' in prompt
    assert '"value": 0.0' in prompt
    assert '"curiosity": 0.82' in prompt
    assert "value=0.0" in prompt
    assert "target_evidenceを上書きしない" in prompt


def test_validator_prompt_rejects_positive_target_claim_against_zero_evidence() -> None:
    prompt = ResponseValidatorPromptBuilder().build(
        _context("joy"),
        CharacterResponse(
            speech="うん、少し楽しいよ。",
            claims=(ResponseClaim.CONVERSATION_ONLY,),
        ),
    )

    assert "# Target-specific Internal State Truth Check" in prompt
    assert '"path": "emotion.current.reactive.joy"' in prompt
    assert '"value": 0.0' in prompt
    assert "少しでも存在する" in prompt
    assert "accepted=false" in prompt
    assert "curiosity、engagement、energy等はjoy、anger等の代替事実ではない" in prompt


def test_target_conflict_regeneration_does_not_compensate_with_other_state() -> None:
    correction = json.dumps(
        {
            "reason": "target_joy_value_conflict",
            "instruction": "未実行処理を実行済みと表現しない",
        },
        ensure_ascii=False,
    )

    prompt = CharacterPromptBuilder().build(
        _context("joy"),
        character_profile=None,
        correction=correction,
    )

    assert "# Target-specific Internal State Regeneration" in prompt
    assert "target_evidenceと矛盾しない形へ修正" in prompt
    assert "付け足して埋め合わせない" in prompt
    assert "新しい自己状態の事実を作る根拠にはしない" in prompt
    assert "不要な補足を追加せず" in prompt


def test_current_feeling_uses_emotion_overview_instead_of_one_dimension() -> None:
    prompt = CharacterPromptBuilder().build(
        _context("current_feeling"),
        character_profile=None,
        correction=None,
    )

    assert '"scope": "emotion_overview"' in prompt
    assert '"joy": 0.0' in prompt
    assert '"calm": 0.58' in prompt


def test_current_desire_uses_existing_primary_desire_when_available() -> None:
    prompt = CharacterPromptBuilder().build(
        _context(
            "current_desire",
            memory={
                "response_content_plan": {
                    "primary_desire": "connection",
                    "conversation_strategies": ["continue_conversation"],
                }
            },
        ),
        character_profile=None,
        correction=None,
    )

    assert '"scope": "exact_dimension"' in prompt
    assert '"path": "memory.response_content_plan.primary_desire"' in prompt
    assert '"value": "connection"' in prompt


def test_non_internal_state_target_does_not_add_target_evidence_section() -> None:
    meaning = StructuredInputMeaning(
        input_speech_act=InputSpeechAct.QUESTION,
        primary_intent="ask_topic",
        expected_response=ExpectedResponse.DIRECT_ANSWER,
        target=InputTarget("topic", "ocean"),
        confidence=0.99,
    )
    directive = InternalDirective(
        response_mode=ResponseMode.ANSWER,
        response_goal="質問へ直接答える",
        activity_intent=None,
        initiative_level=0.2,
        question_budget=0,
        new_direction_budget=0,
        self_disclosure_level=0.2,
    )
    context = ResponseContext(
        user_input="海は好き？",
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.WAITING_INPUT,
        failure_reason=None,
        result_summary="",
        allowed_claims=(ResponseClaim.CONVERSATION_ONLY,),
        forbidden_claims=(),
        activity_goal="質問へ直接答える",
        constraints={
            "_internal_directive": ValidatedActionPlan(
                meaning=meaning,
                directive=directive,
            ).as_context()
        },
    )

    prompt = CharacterPromptBuilder().build(
        context,
        character_profile=None,
        correction=None,
    )

    assert "# Target-specific Internal State Evidence" not in prompt
