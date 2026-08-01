from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.domain.response_content_plan import ResponseContentPlan


class ResponseContentPlanner:
    """Motivation・Moralの観測値を発話専用の有限な方針へ変換する。"""

    _KNOWN_STRATEGIES = frozenset(
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
    _SECURITY_CONFLICTS = frozenset(
        {
            "connection_security_tension",
            "expression_security_tension",
            "curiosity_security_tension",
        }
    )

    def build(
        self,
        *,
        motivation: Mapping[str, object] | None,
        moral: Mapping[str, object] | None,
    ) -> ResponseContentPlan:
        motivation_data = motivation or {}
        moral_data = moral or {}
        primary_desire = self._optional_text(
            motivation_data.get("primary_desire")
        )
        expression_strength = self._number(
            motivation_data.get("expression_strength"),
            default=0.5,
        )
        conflict_mode = self._primary_conflict(motivation_data.get("conflicts"))
        strategies = self._strategies(
            motivation_data.get("recommended_conversation_strategies"),
            conflict_mode=conflict_mode,
            moral=moral_data,
        )
        values = self._value_emphases(
            primary_desire=primary_desire,
            moral=moral_data,
        )
        interpersonal_stance = self._interpersonal_stance(
            primary_desire=primary_desire,
            moral=moral_data,
        )
        expression_mode = (
            "restrained"
            if expression_strength <= 0.35
            else "open"
            if expression_strength >= 0.70
            else "balanced"
        )
        self_disclosure = (
            "brief"
            if "self_disclose_briefly" in strategies
            and expression_mode != "restrained"
            else "none"
        )
        reasons = [
            "motivation_projected_to_response_content",
            "moral_projected_as_value_emphasis",
            "selection_and_execution_boundaries_unchanged",
        ]
        if conflict_mode is not None:
            reasons.append(conflict_mode)

        return ResponseContentPlan(
            primary_desire=primary_desire,
            conversation_strategies=strategies,
            value_emphases=values,
            interpersonal_stance=interpersonal_stance,
            expression_mode=expression_mode,
            self_disclosure_level=self_disclosure,
            conflict_mode=conflict_mode,
            question_budget=(
                1 if any(item in self._QUESTION_STRATEGIES for item in strategies) else 0
            ),
            new_direction_budget=(
                1
                if any(item in self._NEW_DIRECTION_STRATEGIES for item in strategies)
                else 0
            ),
            observation_only=True,
            reasons=tuple(reasons),
        )

    def _strategies(
        self,
        value: object,
        *,
        conflict_mode: str | None,
        moral: Mapping[str, object],
    ) -> tuple[str, ...]:
        base: list[str] = []
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for item in value:
                if not isinstance(item, str):
                    continue
                normalized = item.strip()
                if normalized in self._KNOWN_STRATEGIES and normalized not in base:
                    base.append(normalized)
                if len(base) >= 3:
                    break

        state = self._mapping(moral.get("state"))
        aggressive_impulse = self._number(
            state.get("aggressive_impulse"),
            default=0.0,
        )
        restraint = self._number(state.get("restraint"), default=0.5)
        priorities: list[str] = []
        if conflict_mode in self._SECURITY_CONFLICTS:
            priorities.append("slow_down")
        if aggressive_impulse >= 0.55 and restraint >= 0.50:
            priorities.append("state_boundary_calmly")

        priorities = list(dict.fromkeys(priorities))[:3]
        remaining_slots = max(0, 3 - len(priorities))
        retained_base = [item for item in base if item not in priorities][
            :remaining_slots
        ]
        result = [*retained_base, *priorities]
        if not result:
            result.append("continue_conversation")
        return tuple(result)

    def _value_emphases(
        self,
        *,
        primary_desire: str | None,
        moral: Mapping[str, object],
    ) -> tuple[str, ...]:
        profile = self._mapping(moral.get("profile"))
        state = self._mapping(moral.get("state"))
        composite = self._mapping(moral.get("composite"))
        candidates: list[tuple[str, float]] = [
            (
                "compassion",
                max(
                    self._number(profile.get("compassion"), default=0.0),
                    self._number(state.get("empathy_activation"), default=0.0),
                    self._number(
                        composite.get("prosocial_activation"), default=0.0
                    ),
                ),
            ),
            ("honesty", self._number(profile.get("honesty"), default=0.0)),
            ("fairness", self._number(profile.get("fairness"), default=0.0)),
            (
                "restraint",
                max(
                    self._number(state.get("restraint"), default=0.0),
                    self._number(
                        composite.get("effective_restraint"), default=0.0
                    ),
                ),
            ),
            ("respect", self._number(profile.get("rule_respect"), default=0.0)),
        ]
        ranked = [
            name
            for name, score in sorted(candidates, key=lambda item: (-item[1], item[0]))
            if score >= 0.58
        ]
        if primary_desire == "autonomy":
            ranked.insert(0, "autonomy")
        elif primary_desire == "achievement":
            ranked.insert(0, "achievement")
        return tuple(dict.fromkeys(ranked))[:3]

    def _interpersonal_stance(
        self,
        *,
        primary_desire: str | None,
        moral: Mapping[str, object],
    ) -> str:
        state = self._mapping(moral.get("state"))
        composite = self._mapping(moral.get("composite"))
        empathy = self._number(state.get("empathy_activation"), default=0.0)
        prosocial = self._number(
            composite.get("prosocial_activation"), default=0.0
        )
        aggressive = self._number(state.get("aggressive_impulse"), default=0.0)
        if aggressive >= 0.55 or primary_desire == "security":
            return "guarded"
        if empathy >= 0.60 or prosocial >= 0.60:
            return "supportive"
        return "balanced"

    @classmethod
    def _primary_conflict(cls, value: object) -> str | None:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            return None
        for item in value:
            if not isinstance(item, Mapping):
                continue
            reason = cls._optional_text(item.get("reason"))
            if reason is not None:
                return reason
        return None

    @staticmethod
    def _mapping(value: object) -> Mapping[str, object]:
        return value if isinstance(value, Mapping) else {}

    @staticmethod
    def _optional_text(value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @staticmethod
    def _number(value: object, *, default: float) -> float:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return max(0.0, min(1.0, float(value)))
        return default
