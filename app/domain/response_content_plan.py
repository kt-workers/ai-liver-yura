from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


_ALLOWED_STRATEGIES = frozenset(
    {
        "continue_conversation",
        "acknowledge_other",
        "ask_follow_up",
        "ask_for_detail",
        "explore_related_topic",
        "observe_before_speaking",
        "share_reaction",
        "self_disclose_briefly",
        "state_preference",
        "offer_help",
        "explain_clearly",
        "confirm_contribution",
        "propose_direction",
        "take_initiative",
        "state_choice",
        "set_boundary",
        "state_boundary_calmly",
        "slow_down",
        "seek_clarification",
        "define_next_step",
        "summarize_progress",
        "complete_current_goal",
    }
)
_ALLOWED_VALUES = frozenset(
    {
        "compassion",
        "honesty",
        "fairness",
        "restraint",
        "respect",
        "autonomy",
        "achievement",
    }
)
_ALLOWED_STANCES = frozenset({"supportive", "balanced", "guarded"})
_ALLOWED_EXPRESSION_MODES = frozenset({"restrained", "balanced", "open"})
_ALLOWED_SELF_DISCLOSURE = frozenset({"none", "brief"})


@dataclass(frozen=True, slots=True)
class ResponseContentPlan:
    """確定済み事実を変えず、Character LLMの表現方針だけを案内する。"""

    primary_desire: str | None = None
    conversation_strategies: tuple[str, ...] = ()
    value_emphases: tuple[str, ...] = ()
    interpersonal_stance: str = "balanced"
    expression_mode: str = "balanced"
    self_disclosure_level: str = "none"
    conflict_mode: str | None = None
    question_budget: int = 0
    new_direction_budget: int = 0
    observation_only: bool = True
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if len(self.conversation_strategies) > 3:
            raise ValueError("conversation_strategiesは3件以下にしてください。")
        if len(set(self.conversation_strategies)) != len(
            self.conversation_strategies
        ):
            raise ValueError("conversation_strategiesは重複できません。")
        if any(
            strategy not in _ALLOWED_STRATEGIES
            for strategy in self.conversation_strategies
        ):
            raise ValueError("未定義のconversation strategyは使用できません。")
        if len(self.value_emphases) > 3:
            raise ValueError("value_emphasesは3件以下にしてください。")
        if len(set(self.value_emphases)) != len(self.value_emphases):
            raise ValueError("value_emphasesは重複できません。")
        if any(value not in _ALLOWED_VALUES for value in self.value_emphases):
            raise ValueError("未定義のvalue emphasisは使用できません。")
        if self.interpersonal_stance not in _ALLOWED_STANCES:
            raise ValueError("interpersonal_stanceが不正です。")
        if self.expression_mode not in _ALLOWED_EXPRESSION_MODES:
            raise ValueError("expression_modeが不正です。")
        if self.self_disclosure_level not in _ALLOWED_SELF_DISCLOSURE:
            raise ValueError("self_disclosure_levelが不正です。")
        if self.question_budget not in {0, 1}:
            raise ValueError("question_budgetは0または1にしてください。")
        if self.new_direction_budget not in {0, 1}:
            raise ValueError("new_direction_budgetは0または1にしてください。")
        if not self.observation_only:
            raise ValueError("Response Content Planは観測・表現専用です。")
        if any(not reason.strip() for reason in self.reasons):
            raise ValueError("reasonsに空文字は使用できません。")

    def as_context(self) -> dict[str, object]:
        return {
            "primary_desire": self.primary_desire,
            "conversation_strategies": list(self.conversation_strategies),
            "value_emphases": list(self.value_emphases),
            "interpersonal_stance": self.interpersonal_stance,
            "expression_mode": self.expression_mode,
            "self_disclosure_level": self.self_disclosure_level,
            "conflict_mode": self.conflict_mode,
            "question_budget": self.question_budget,
            "new_direction_budget": self.new_direction_budget,
            "observation_only": self.observation_only,
            "reasons": list(self.reasons),
        }

    @classmethod
    def from_context(cls, value: object) -> ResponseContentPlan:
        """境界を越えたdictを保守的に型付きPlanへ戻す。"""

        if not isinstance(value, Mapping):
            return cls(reasons=("response_content_plan_unavailable",))

        strategies = cls._known_values(
            value.get("conversation_strategies"),
            allowed=_ALLOWED_STRATEGIES,
            limit=3,
        )
        emphases = cls._known_values(
            value.get("value_emphases"),
            allowed=_ALLOWED_VALUES,
            limit=3,
        )
        stance = str(value.get("interpersonal_stance") or "balanced")
        expression_mode = str(value.get("expression_mode") or "balanced")
        self_disclosure = str(value.get("self_disclosure_level") or "none")
        reasons = tuple(
            str(item).strip()
            for item in value.get("reasons", ())
            if isinstance(item, str) and item.strip()
        ) if isinstance(value.get("reasons", ()), (list, tuple)) else ()

        return cls(
            primary_desire=(
                str(value["primary_desire"]).strip()
                if value.get("primary_desire") is not None
                and str(value["primary_desire"]).strip()
                else None
            ),
            conversation_strategies=strategies,
            value_emphases=emphases,
            interpersonal_stance=(
                stance if stance in _ALLOWED_STANCES else "balanced"
            ),
            expression_mode=(
                expression_mode
                if expression_mode in _ALLOWED_EXPRESSION_MODES
                else "balanced"
            ),
            self_disclosure_level=(
                self_disclosure
                if self_disclosure in _ALLOWED_SELF_DISCLOSURE
                else "none"
            ),
            conflict_mode=(
                str(value["conflict_mode"]).strip()
                if value.get("conflict_mode") is not None
                and str(value["conflict_mode"]).strip()
                else None
            ),
            question_budget=1 if value.get("question_budget") == 1 else 0,
            new_direction_budget=(
                1 if value.get("new_direction_budget") == 1 else 0
            ),
            observation_only=True,
            reasons=reasons or ("response_content_plan_restored",),
        )

    @staticmethod
    def _known_values(
        value: object,
        *,
        allowed: frozenset[str],
        limit: int,
    ) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            return ()
        result: list[str] = []
        for item in value:
            if not isinstance(item, str):
                continue
            normalized = item.strip()
            if normalized in allowed and normalized not in result:
                result.append(normalized)
            if len(result) >= limit:
                break
        return tuple(result)
