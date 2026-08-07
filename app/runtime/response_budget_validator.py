from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.character_response import ResponseContext, ResponseValidationResult
from app.utils.trace import TraceLogger

_QUOTED_SPAN_PATTERN = re.compile(
    r"「[^」]*」|『[^』]*』|“[^”]*”|\"[^\"\n]*\"|'[^'\n]*'"
)
_SENTENCE_BOUNDARY_PATTERN = re.compile(r"(?<=[。！？!?])|\n+")
_DIRECTED_QUESTION_ENDING_PATTERN = re.compile(
    r"(?:ですか|ますか|でしょうか|だろうか|かい|教えて|聞かせて)[。！!]*$"
)
_EXPLICIT_NEW_DIRECTION_PATTERN = re.compile(
    r"(?:ところで|そういえば|ちなみに|話は変わる|別の話(?:だけど|を|に))"
)


@dataclass(frozen=True, slots=True)
class ResponseSpeechActAnalysis:
    """発話本文から、相手へ向けた質問と明示的な話題展開だけを抽出する。"""

    directed_question_count: int
    explicit_new_direction_count: int
    directed_question_evidence: tuple[str, ...] = ()
    explicit_new_direction_evidence: tuple[str, ...] = ()


class ResponseSpeechActAnalyzer:
    """文字上の疑問表現と、返答を要求する質問行為を区別する。"""

    def analyze(self, speech: str) -> ResponseSpeechActAnalysis:
        normalized = speech.strip()
        if not normalized:
            return ResponseSpeechActAnalysis(0, 0)

        unquoted = _QUOTED_SPAN_PATTERN.sub("", normalized)
        question_evidence = tuple(
            sentence
            for sentence in self._sentences(unquoted)
            if self._is_directed_question(sentence)
        )
        new_direction_evidence = tuple(
            match.group(0)
            for match in _EXPLICIT_NEW_DIRECTION_PATTERN.finditer(unquoted)
        )
        return ResponseSpeechActAnalysis(
            directed_question_count=len(question_evidence),
            explicit_new_direction_count=len(new_direction_evidence),
            directed_question_evidence=question_evidence,
            explicit_new_direction_evidence=new_direction_evidence,
        )

    @staticmethod
    def _sentences(speech: str) -> tuple[str, ...]:
        return tuple(
            sentence.strip()
            for sentence in _SENTENCE_BOUNDARY_PATTERN.split(speech)
            if sentence.strip()
        )

    @staticmethod
    def _is_directed_question(sentence: str) -> bool:
        if "?" in sentence or "？" in sentence:
            return True
        return _DIRECTED_QUESTION_ENDING_PATTERN.search(sentence) is not None


class ResponseBudgetValidator:
    """Internal Directiveの質問・話題展開予算を発話行為として検証する。"""

    def __init__(
        self,
        analyzer: ResponseSpeechActAnalyzer | None = None,
    ) -> None:
        self._analyzer = analyzer or ResponseSpeechActAnalyzer()
        self._trace_logger = TraceLogger()

    def validate(
        self,
        context: ResponseContext,
        speech: str,
    ) -> ResponseValidationResult:
        envelope_value = context.constraints.get("_internal_directive")
        if not isinstance(envelope_value, dict):
            return ResponseValidationResult(True, "response_budget_not_configured")

        internal_value = envelope_value.get("internal_directive")
        meaning_value = envelope_value.get("structured_input_meaning")
        if not isinstance(internal_value, dict):
            return ResponseValidationResult(True, "response_budget_not_configured")

        internal = dict(internal_value)
        meaning = dict(meaning_value) if isinstance(meaning_value, dict) else {}
        analysis = self._analyzer.analyze(speech)
        reasons: list[str] = []

        question_budget = 1 if internal.get("question_budget") == 1 else 0
        if analysis.directed_question_count > question_budget:
            reasons.append("response_exceeds_internal_directive_question_budget")

        new_direction_budget = (
            1 if internal.get("new_direction_budget") == 1 else 0
        )
        if analysis.explicit_new_direction_count > new_direction_budget:
            reasons.append(
                "response_exceeds_internal_directive_new_direction_budget"
            )

        speech_act = str(meaning.get("input_speech_act") or "").strip().lower()
        phase = str(meaning.get("conversation_phase_signal") or "").strip().lower()
        if speech_act == "closing" or phase == "winding_down":
            if analysis.directed_question_count:
                reasons.append("closing_response_reopens_conversation")
            if len(speech.strip()) > 80:
                reasons.append("closing_response_too_long")

        reasons_tuple = tuple(dict.fromkeys(reasons))
        accepted = not reasons_tuple
        result = ResponseValidationResult(
            accepted=accepted,
            reason=("response_budget_valid" if accepted else reasons_tuple[0]),
            claim_differences=reasons_tuple,
        )
        fields = {
            "activity_type": context.activity_type,
            "operation": context.operation,
            "question_budget": question_budget,
            "new_direction_budget": new_direction_budget,
            "directed_question_count": analysis.directed_question_count,
            "explicit_new_direction_count": analysis.explicit_new_direction_count,
            "accepted": accepted,
            "reasons": list(reasons_tuple),
        }
        if accepted:
            self._trace_logger.debug("response_budget_validator:accepted", **fields)
        else:
            self._trace_logger.info("response_budget_validator:rejected", **fields)
        return result
