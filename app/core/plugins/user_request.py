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
    """LLM失敗時に使う、高確信度の実行・停止要求だけを判定するFallback。"""

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

    # 「どんな」「教えて」、疑問符、語尾、過去表現、仮定表現などは、
    # 会話履歴を含むInput Meaning Interpreterで解釈する。
    return UserRequestInterpretation(
        UserRequestKind.AMBIGUOUS,
        0.0,
        "semantic_interpretation_required",
    )
