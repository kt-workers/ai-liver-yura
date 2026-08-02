from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class UserRequestKind(str, Enum):
    EXECUTION = "execution"
    KNOWLEDGE = "knowledge"
    PAST_EVENT = "past_event"
    NEGATIVE = "negative"
    CHAT = "chat"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class UserRequestInterpretation:
    kind: UserRequestKind
    confidence: float
    reason: str


def interpret_user_request(text: str) -> UserRequestInterpretation:
    """LLM失敗時に使う、高確信度の明示表現だけを判定するFallback。"""

    normalized = text.strip()
    if not normalized:
        return UserRequestInterpretation(UserRequestKind.AMBIGUOUS, 0.0, "empty_input")

    if any(
        marker in normalized
        for marker in ("したくない", "しないで", "やめて", "停止して", "中止して")
    ):
        return UserRequestInterpretation(
            UserRequestKind.NEGATIVE,
            0.95,
            "explicit_stop_or_negative_request",
        )

    if _is_explicit_knowledge_question(normalized):
        return UserRequestInterpretation(
            UserRequestKind.KNOWLEDGE,
            0.95,
            "explicit_definition_rule_or_difficulty_question_fallback",
        )

    if _is_explicit_past_event_reference(normalized):
        return UserRequestInterpretation(
            UserRequestKind.PAST_EVENT,
            0.9,
            "explicit_past_event_reference_fallback",
        )

    if _is_explicit_participation_proposal(normalized):
        return UserRequestInterpretation(
            UserRequestKind.EXECUTION,
            0.9,
            "explicit_participation_proposal_fallback",
        )

    if normalized.endswith(
        (
            "してください",
            "始めよう",
            "検索して",
            "聞いて",
            "開始して",
            "停止して",
            "中止して",
        )
    ):
        return UserRequestInterpretation(
            UserRequestKind.EXECUTION,
            0.9,
            "explicit_action_request_fallback",
        )

    # 「どんな」、一般的な「教えて」、疑問符、語尾、仮定表現などは、
    # 会話履歴を含むInput Meaning Interpreterで解釈する。
    return UserRequestInterpretation(
        UserRequestKind.AMBIGUOUS,
        0.0,
        "semantic_interpretation_required",
    )


def _is_explicit_knowledge_question(text: str) -> bool:
    if any(
        marker in text
        for marker in (
            "って何",
            "とは何",
            "ルールを教えて",
            "仕組みを教えて",
            "意味を教えて",
        )
    ):
        return True
    return text.endswith(("は難しい？", "は難しい?", "のは難しい？", "のは難しい?"))


def _is_explicit_past_event_reference(text: str) -> bool:
    if not any(
        marker in text
        for marker in ("昨日", "一昨日", "先週", "この前", "以前", "さっき")
    ):
        return False
    return any(
        marker in text
        for marker in (
            "をした",
            "をやった",
            "を始めた",
            "に行った",
            "を見た",
            "を聞いた",
        )
    )


def _is_explicit_participation_proposal(text: str) -> bool:
    """共同実行を直接提案する語尾だけを、LLM失敗時の実行要求として扱う。"""

    return text.endswith(
        (
            "しませんか？",
            "しませんか?",
            "しない？",
            "しない?",
            "しよう",
            "しようよ",
            "しようか",
            "しようか？",
            "しようか?",
            "やろう",
            "遊ぼう",
            "付き合って",
        )
    )
