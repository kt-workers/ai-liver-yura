from __future__ import annotations

import pytest

from app.domain.activities import Activity, ActivityType
from app.domain.character_response import (
    ActivityExecutionStatus,
    CharacterResponse,
    ResponseClaim,
    ResponseContext,
)
from app.runtime.character_response_pipeline import ResponseValidator
from app.runtime.response_budget_validator import (
    ResponseBudgetValidator,
    ResponseSpeechActAnalyzer,
)

pytestmark = pytest.mark.unit


def _context(
    *,
    question_budget: int = 0,
    new_direction_budget: int = 0,
    input_speech_act: str = "question",
    conversation_phase_signal: str = "active",
) -> ResponseContext:
    return ResponseContext(
        user_input="今どんな気分？",
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.WAITING_INPUT,
        failure_reason=None,
        result_summary="内部状態について直接回答する",
        allowed_claims=(ResponseClaim.CONVERSATION_ONLY,),
        forbidden_claims=(),
        activity_goal="ユーザーの質問へ直接回答する",
        constraints={
            "_internal_directive": {
                "internal_directive": {
                    "question_budget": question_budget,
                    "new_direction_budget": new_direction_budget,
                    "forbidden_claims": [],
                },
                "structured_input_meaning": {
                    "input_speech_act": input_speech_act,
                    "conversation_phase_signal": conversation_phase_signal,
                },
                "existence_boundaries": [],
            }
        },
    )


def _activity() -> Activity:
    return Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="内部状態について直接回答する",
    )


def test_self_reflective_kana_is_not_counted_as_directed_question() -> None:
    speech = (
        "落ち着いた感じで言うと、今は好奇心がほどほどにあって、"
        "いろんなことにちょっとずつ興味がある感じかな。"
        "焦らずゆったりと、気になることを見つけていきたい気分だよ。"
    )

    analysis = ResponseSpeechActAnalyzer().analyze(speech)

    assert analysis.directed_question_count == 0
    assert analysis.directed_question_evidence == ()


def test_noun_phrase_containing_question_word_is_not_a_question() -> None:
    analysis = ResponseSpeechActAnalyzer().analyze(
        "今は気になることを少しずつ見つけていきたい気分だよ。"
    )

    assert analysis.directed_question_count == 0


@pytest.mark.parametrize(
    "speech",
    [
        "どう思う？",
        "今日は何を話しますか。",
        "もう少し詳しく教えて。",
        "そのときのことを聞かせて。",
    ],
)
def test_actual_directed_question_is_counted(speech: str) -> None:
    analysis = ResponseSpeechActAnalyzer().analyze(speech)

    assert analysis.directed_question_count == 1


def test_question_inside_quote_is_not_counted_as_new_question() -> None:
    analysis = ResponseSpeechActAnalyzer().analyze(
        "『どう思う？』と聞かれたから、少し考えてみたよ。"
    )

    assert analysis.directed_question_count == 0


def test_direct_answer_is_accepted_when_question_budget_is_zero() -> None:
    speech = (
        "落ち着いた感じで言うと、今は好奇心がほどほどにあって、"
        "いろんなことにちょっとずつ興味がある感じかな。"
    )

    result = ResponseBudgetValidator().validate(_context(), speech)

    assert result.accepted is True
    assert result.reason == "response_budget_valid"


def test_actual_question_is_rejected_when_question_budget_is_zero() -> None:
    result = ResponseBudgetValidator().validate(
        _context(),
        "今は落ち着いているよ。あなたはどう思う？",
    )

    assert result.accepted is False
    assert result.reason == "response_exceeds_internal_directive_question_budget"


def test_explicit_topic_change_uses_separate_new_direction_budget() -> None:
    result = ResponseBudgetValidator().validate(
        _context(question_budget=1, new_direction_budget=0),
        "ちなみに、別の話もしてみようか？",
    )

    assert result.accepted is False
    assert "response_exceeds_internal_directive_new_direction_budget" in (
        result.claim_differences
    )


def test_closing_response_does_not_reopen_for_quoted_question() -> None:
    result = ResponseBudgetValidator().validate(
        _context(
            question_budget=0,
            input_speech_act="closing",
            conversation_phase_signal="winding_down",
        ),
        "『また話せる？』って言葉、覚えておくね。おやすみ。",
    )

    assert result.accepted is True


@pytest.mark.asyncio
async def test_response_validator_adopts_direct_answer_without_regeneration() -> None:
    response = CharacterResponse(
        speech=(
            "今は好奇心がほどほどにあって、"
            "いろんなことに少しずつ興味がある感じかな。"
        )
    )

    result = await ResponseValidator().validate(
        _activity(),
        _context(),
        response,
    )

    assert result.accepted is True
    assert result.reason == "deterministic_facts_valid"
