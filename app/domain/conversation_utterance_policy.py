from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import Enum

from app.domain.response_content_plan import ResponseContentPlan


_QUESTION_STRATEGIES = frozenset(
    {"ask_follow_up", "ask_for_detail", "seek_clarification"}
)
_NEW_DIRECTION_STRATEGIES = frozenset(
    {
        "explore_related_topic",
        "propose_direction",
        "take_initiative",
        "define_next_step",
    }
)
_LISTEN_STRATEGIES = frozenset(
    {
        "acknowledge_other",
        "continue_conversation",
        "observe_before_speaking",
        "slow_down",
    }
)
_REACTION_STRATEGIES = frozenset(
    {
        "share_reaction",
        "acknowledge_other",
        "continue_conversation",
        "state_preference",
    }
)
_ANSWER_STRATEGIES = frozenset(
    {
        "continue_conversation",
        "acknowledge_other",
        "state_preference",
        "offer_help",
        "explain_clearly",
        "confirm_contribution",
        "state_choice",
        "set_boundary",
        "state_boundary_calmly",
        "slow_down",
        "summarize_progress",
        "complete_current_goal",
    }
)
_OBSERVE_STRATEGIES = frozenset(
    {
        "observe_before_speaking",
        "acknowledge_other",
        "continue_conversation",
        "slow_down",
    }
)
_SPEAK_STRATEGIES = frozenset(
    {
        "explore_related_topic",
        "self_disclose_briefly",
        "state_preference",
        "offer_help",
        "explain_clearly",
        "confirm_contribution",
        "propose_direction",
        "take_initiative",
        "state_choice",
        "define_next_step",
        "summarize_progress",
        "complete_current_goal",
    }
)
_ACKNOWLEDGEMENT_CLAUSES = frozenset(
    {
        "うん",
        "うんうん",
        "はい",
        "そう",
        "そうだね",
        "そうだよね",
        "そうなんだ",
        "そうか",
        "そうかも",
        "だよね",
        "なるほど",
        "ふむ",
        "ふむふむ",
        "へえ",
        "ほう",
        "いいね",
        "それいいね",
        "それはいいね",
        "いいと思う",
        "わかる",
        "わかるよ",
        "たしかに",
        "確かに",
        "ほんとだね",
        "本当だね",
        "前向きでいいね",
        "そういうの",
        "そういうのいいね",
        "了解",
        "わかった",
        "ok",
        "okay",
        "yes",
    }
)
_ACKNOWLEDGEMENT_SPLIT_PATTERN = re.compile(r"[。.!！、,\n]+")


class ConversationResponseMode(str, Enum):
    """Character発話で今回どの関わり方を取るかを表す。"""

    ANSWER = "answer"
    ASK = "ask"
    LISTEN = "listen"
    REACT = "react"
    SPEAK = "speak"
    OBSERVE = "observe"


@dataclass(frozen=True, slots=True)
class ConversationResponseDecision:
    """内的状態と会話状況から導出した今回の応答モード。"""

    mode: ConversationResponseMode
    confidence: float
    scores: tuple[tuple[str, float], ...]
    reasons: tuple[str, ...]
    low_information_input: bool

    def as_context(self) -> dict[str, object]:
        return {
            "mode": self.mode.value,
            "confidence": self.confidence,
            "scores": {name: score for name, score in self.scores},
            "reasons": list(self.reasons),
            "low_information_input": self.low_information_input,
        }


def is_low_information_acknowledgement(user_input: str) -> bool:
    """互換用の表面判定。RuntimeのMode選択では使用しない。"""

    normalized = unicodedata.normalize("NFKC", user_input).strip().lower()
    if not normalized or "?" in normalized or "？" in normalized:
        return False
    if len(normalized) > 32:
        return False

    clauses = tuple(
        clause.strip(" 〜~")
        for clause in _ACKNOWLEDGEMENT_SPLIT_PATTERN.split(normalized)
        if clause.strip(" 〜~")
    )
    if not clauses or len(clauses) > 2:
        return False
    return all(clause in _ACKNOWLEDGEMENT_CLAUSES for clause in clauses)


def decide_conversation_response_mode(
    plan: ResponseContentPlan,
    *,
    speech_act: str,
    conversation_phase: str,
    initiative_level: float,
    user_input: str = "",
    drive: Mapping[str, object] | None = None,
) -> ConversationResponseDecision:
    """LLM意味解析結果と内的状態を重み付けし、応答モードを選ぶ。"""

    del user_input  # 表面テキストを決定論的に再解釈しない。
    normalized_speech_act = speech_act.strip().lower()
    normalized_phase = conversation_phase.strip().lower()
    initiative = _clamp_01(initiative_level)
    low_information = normalized_speech_act == "acknowledgement"
    drive_values = drive or {}
    curiosity = _number(drive_values.get("curiosity"), default=0.5)
    engagement = _number(drive_values.get("engagement"), default=0.5)
    boredom = _number(drive_values.get("boredom"), default=0.0)
    energy = _number(drive_values.get("energy"), default=0.7)

    scores = {
        ConversationResponseMode.ANSWER: -0.20,
        ConversationResponseMode.ASK: 0.05 + 0.20 * initiative,
        ConversationResponseMode.LISTEN: 0.15 + 0.25 * (1.0 - initiative),
        ConversationResponseMode.REACT: 0.20,
        ConversationResponseMode.SPEAK: 0.10 + 0.25 * initiative,
        ConversationResponseMode.OBSERVE: 0.10 + 0.25 * (1.0 - initiative),
    }
    reasons: list[str] = []

    strategies = set(plan.conversation_strategies)
    if strategies & _QUESTION_STRATEGIES:
        scores[ConversationResponseMode.ASK] += 0.45
        reasons.append("question_strategy_available")
    if "explore_related_topic" in strategies:
        scores[ConversationResponseMode.ASK] += 0.15
        scores[ConversationResponseMode.SPEAK] += 0.25
    if strategies & _LISTEN_STRATEGIES:
        scores[ConversationResponseMode.LISTEN] += 0.30
        reasons.append("listening_strategy_available")
    if strategies & _REACTION_STRATEGIES:
        scores[ConversationResponseMode.REACT] += 0.35
        reasons.append("reaction_strategy_available")
    if strategies & _SPEAK_STRATEGIES:
        scores[ConversationResponseMode.SPEAK] += 0.30
        reasons.append("speaking_strategy_available")
    if "observe_before_speaking" in strategies or "slow_down" in strategies:
        scores[ConversationResponseMode.OBSERVE] += 0.35
        reasons.append("observation_strategy_available")

    if plan.question_budget == 1:
        scores[ConversationResponseMode.ASK] += 0.25
        reasons.append("question_budget_available")
    else:
        scores[ConversationResponseMode.ASK] -= 0.10
    if plan.new_direction_budget == 1:
        scores[ConversationResponseMode.SPEAK] += 0.20
        reasons.append("new_direction_budget_available")

    scores[ConversationResponseMode.ASK] += 0.40 * curiosity
    scores[ConversationResponseMode.ASK] += 0.12 * engagement
    scores[ConversationResponseMode.ASK] += 0.20 * boredom
    scores[ConversationResponseMode.ASK] += 0.10 * energy
    scores[ConversationResponseMode.LISTEN] += 0.20 * engagement
    scores[ConversationResponseMode.REACT] += 0.18 * engagement
    scores[ConversationResponseMode.SPEAK] += 0.35 * boredom
    scores[ConversationResponseMode.SPEAK] += 0.15 * energy
    scores[ConversationResponseMode.OBSERVE] += 0.25 * (1.0 - energy)

    primary_desire = (plan.primary_desire or "").strip().lower()
    if primary_desire == "curiosity":
        scores[ConversationResponseMode.ASK] += 0.25
        reasons.append("curiosity_desire_supports_asking")
    elif primary_desire == "connection":
        scores[ConversationResponseMode.LISTEN] += 0.25
        scores[ConversationResponseMode.ASK] += 0.15
        reasons.append("connection_desire_supports_engagement")
    elif primary_desire == "expression":
        scores[ConversationResponseMode.REACT] += 0.30
        scores[ConversationResponseMode.SPEAK] += 0.20
        reasons.append("expression_desire_supports_reaction")
    elif primary_desire == "security":
        scores[ConversationResponseMode.OBSERVE] += 0.35
        scores[ConversationResponseMode.LISTEN] += 0.20
        scores[ConversationResponseMode.ASK] -= 0.15
        reasons.append("security_desire_supports_observation")
    elif primary_desire in {"autonomy", "achievement", "recognition"}:
        scores[ConversationResponseMode.SPEAK] += 0.30
        reasons.append(f"{primary_desire}_desire_supports_speaking")

    low_initiative_penalty = 0.45 * (1.0 - initiative)
    scores[ConversationResponseMode.ASK] -= low_initiative_penalty
    scores[ConversationResponseMode.SPEAK] -= 0.25 * (1.0 - initiative)

    if normalized_speech_act == "question":
        scores[ConversationResponseMode.ANSWER] += 1.55
        scores[ConversationResponseMode.ASK] -= 0.45
        scores[ConversationResponseMode.SPEAK] -= 0.15
        reasons.append("semantic_question_supports_answer")
    elif normalized_speech_act == "answer":
        scores[ConversationResponseMode.LISTEN] += 0.50
        scores[ConversationResponseMode.REACT] += 0.35
        scores[ConversationResponseMode.SPEAK] += 0.20
        scores[ConversationResponseMode.ASK] -= 0.85
        reasons.append("semantic_answer_returns_conversation_floor")
    elif normalized_speech_act == "acknowledgement":
        scores[ConversationResponseMode.LISTEN] += 0.75
        scores[ConversationResponseMode.REACT] += 0.30
        scores[ConversationResponseMode.ASK] -= 0.40
        scores[ConversationResponseMode.SPEAK] -= 0.40
        curiosity_overflow = max(0.0, curiosity - 0.80)
        if curiosity_overflow > 0.0:
            scores[ConversationResponseMode.ASK] += 2.50 * curiosity_overflow
            reasons.append("strong_curiosity_overcomes_acknowledgement_weight")
        reasons.append("semantic_acknowledgement_supports_listening")
    elif normalized_speech_act == "closing":
        scores[ConversationResponseMode.LISTEN] += 0.80
        scores[ConversationResponseMode.REACT] += 0.55
        scores[ConversationResponseMode.OBSERVE] += 0.35
        scores[ConversationResponseMode.ASK] -= 1.20
        scores[ConversationResponseMode.SPEAK] -= 0.60
        reasons.append("semantic_closing_supports_closure")
    elif normalized_speech_act == "greeting":
        scores[ConversationResponseMode.REACT] += 0.55
        scores[ConversationResponseMode.LISTEN] += 0.25
        scores[ConversationResponseMode.ASK] -= 0.40
        scores[ConversationResponseMode.SPEAK] -= 0.25
        reasons.append("semantic_greeting_supports_brief_reaction")

    if normalized_phase == "greeting":
        scores[ConversationResponseMode.REACT] += 0.25
        scores[ConversationResponseMode.ASK] -= 0.20
        reasons.append("greeting_phase_supports_reaction")
    elif normalized_phase == "winding_down":
        scores[ConversationResponseMode.LISTEN] += 0.45
        scores[ConversationResponseMode.REACT] += 0.30
        scores[ConversationResponseMode.OBSERVE] += 0.20
        scores[ConversationResponseMode.ASK] -= 0.70
        scores[ConversationResponseMode.SPEAK] -= 0.35
        reasons.append("winding_down_phase_supports_closure")

    ordered_modes = (
        ConversationResponseMode.ANSWER,
        ConversationResponseMode.LISTEN,
        ConversationResponseMode.REACT,
        ConversationResponseMode.ASK,
        ConversationResponseMode.SPEAK,
        ConversationResponseMode.OBSERVE,
    )
    ranked = sorted(
        scores.items(),
        key=lambda item: (-item[1], ordered_modes.index(item[0])),
    )
    selected_mode, selected_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else selected_score
    confidence = _clamp_01(0.5 + max(0.0, selected_score - second_score) / 2.0)
    score_context = tuple(
        (mode.value, round(score, 4))
        for mode, score in sorted(scores.items(), key=lambda item: item[0].value)
    )
    return ConversationResponseDecision(
        mode=selected_mode,
        confidence=round(confidence, 4),
        scores=score_context,
        reasons=tuple(dict.fromkeys(reasons))
        or ("state_weighted_default_selection",),
        low_information_input=low_information,
    )


def apply_conversation_response_policy(
    plan: ResponseContentPlan,
    *,
    speech_act: str,
    conversation_phase: str,
    initiative_level: float,
    user_input: str = "",
    drive: Mapping[str, object] | None = None,
) -> tuple[ResponseContentPlan, ConversationResponseDecision]:
    """状態駆動の応答モードを、Character用の実効Planへ投影する。"""

    decision = decide_conversation_response_mode(
        plan,
        speech_act=speech_act,
        conversation_phase=conversation_phase,
        initiative_level=initiative_level,
        user_input=user_input,
        drive=drive,
    )
    mode = decision.mode
    strategies = plan.conversation_strategies
    self_disclosure = plan.self_disclosure_level
    question_budget = plan.question_budget
    new_direction_budget = plan.new_direction_budget

    if mode is ConversationResponseMode.ANSWER:
        strategies = _retain_or_default(
            strategies,
            allowed=_ANSWER_STRATEGIES,
            default="explain_clearly",
        )
        self_disclosure = "none"
        question_budget = 0
        new_direction_budget = 0
    elif mode is ConversationResponseMode.ASK:
        strategies = _retain_or_default(
            strategies,
            allowed=_QUESTION_STRATEGIES | {"acknowledge_other"},
            default="ask_follow_up",
        )
        self_disclosure = "none"
        question_budget = 1
        new_direction_budget = 0
    elif mode is ConversationResponseMode.LISTEN:
        strategies = _retain_or_default(
            strategies,
            allowed=_LISTEN_STRATEGIES,
            default="acknowledge_other",
        )
        self_disclosure = "none"
        question_budget = 0
        new_direction_budget = 0
    elif mode is ConversationResponseMode.REACT:
        strategies = _retain_or_default(
            strategies,
            allowed=_REACTION_STRATEGIES,
            default="share_reaction",
        )
        self_disclosure = "none"
        question_budget = 0
        new_direction_budget = 0
    elif mode is ConversationResponseMode.OBSERVE:
        strategies = _retain_or_default(
            strategies,
            allowed=_OBSERVE_STRATEGIES,
            default="observe_before_speaking",
        )
        self_disclosure = "none"
        question_budget = 0
        new_direction_budget = 0
    else:
        strategies = _retain_or_default(
            strategies,
            allowed=_SPEAK_STRATEGIES | {"continue_conversation", "share_reaction"},
            default="continue_conversation",
        )

    effective_plan = replace(
        plan,
        conversation_strategies=strategies,
        self_disclosure_level=self_disclosure,
        question_budget=question_budget,
        new_direction_budget=new_direction_budget,
        reasons=tuple(
            dict.fromkeys(
                (
                    *plan.reasons,
                    f"conversation_response_mode:{mode.value}",
                )
            )
        ),
    )
    return effective_plan, decision


def constrain_response_content_plan(
    plan: ResponseContentPlan,
    *,
    speech_act: str,
    conversation_phase: str,
    initiative_level: float,
    user_input: str = "",
    drive: Mapping[str, object] | None = None,
) -> ResponseContentPlan:
    """互換API。状態駆動の応答モードを反映した実効Planだけを返す。"""

    effective_plan, _ = apply_conversation_response_policy(
        plan,
        speech_act=speech_act,
        conversation_phase=conversation_phase,
        initiative_level=initiative_level,
        user_input=user_input,
        drive=drive,
    )
    return effective_plan


def _retain_or_default(
    strategies: tuple[str, ...],
    *,
    allowed: frozenset[str],
    default: str,
) -> tuple[str, ...]:
    retained = tuple(item for item in strategies if item in allowed)
    if not retained:
        retained = (default,)
    return tuple(dict.fromkeys(retained))[:3]


def _number(value: object, *, default: float) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _clamp_01(float(value))
    return default


def _clamp_01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
