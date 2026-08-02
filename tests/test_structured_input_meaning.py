from __future__ import annotations

import json

from app.domain.activities import Activity
from app.domain.behavior import SpeechAct
from app.runtime.situation_evaluator import SituationEvaluator


class _UnusedSituationModel:
    async def evaluate(self, activity: Activity) -> str:
        raise AssertionError("parse testではmodelを呼び出さない")


class _UnusedPromptBuilder:
    def build(self, context: object) -> str:
        raise AssertionError("parse testではpromptを構築しない")


def _payload(*, speech_act: str, conversation_phase: str = "active") -> str:
    return json.dumps(
        {
            "decision": "conversation",
            "activity_type": "conversation",
            "operation": "discuss",
            "goal": "ユーザー入力の意味に応じて会話する",
            "constraints": {},
            "speech_act": speech_act,
            "conversation_phase": conversation_phase,
            "initiative_level": 0.5,
            "negated": False,
            "hypothetical": False,
            "past_reference": False,
            "knowledge_question": False,
            "confidence": 0.95,
            "reason": "contextual_semantic_interpretation",
            "ongoing_input_decision": None,
        },
        ensure_ascii=False,
    )


def _evaluator() -> SituationEvaluator:
    return SituationEvaluator(
        _UnusedSituationModel(),
        prompt_builder=_UnusedPromptBuilder(),
    )


def test_parse_accepts_answer_as_contextual_speech_act() -> None:
    analysis = _evaluator().parse(_payload(speech_act="answer"))

    assert analysis is not None
    assert analysis.speech_act is SpeechAct.ANSWER


def test_parse_accepts_acknowledgement_as_contextual_speech_act() -> None:
    analysis = _evaluator().parse(_payload(speech_act="acknowledgement"))

    assert analysis is not None
    assert analysis.speech_act is SpeechAct.ACKNOWLEDGEMENT


def test_parse_accepts_closing_and_winding_down_phase() -> None:
    analysis = _evaluator().parse(
        _payload(speech_act="closing", conversation_phase="winding_down")
    )

    assert analysis is not None
    assert analysis.speech_act is SpeechAct.CLOSING
    assert analysis.conversation_phase == "winding_down"
