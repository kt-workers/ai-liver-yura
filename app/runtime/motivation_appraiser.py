from __future__ import annotations

from collections.abc import Iterable, Mapping

from app.domain.desires import DesireState, DesireType
from app.domain.morals import MoralProfile, MoralState
from app.domain.motivation import DesireConflict, MotivationAppraisal, RankedDesire
from app.domain.relationships import RelationshipState


class MotivationAppraiser:
    """Desire・Relationship・MoralからMotivationを導出する。"""

    _ACTIVITY_RECOMMENDATIONS: Mapping[DesireType, tuple[str, ...]] = {
        DesireType.CONNECTION: (
            "conversation_with_user",
            "stream_comment_response",
            "listening_mode",
        ),
        DesireType.CURIOSITY: (
            "topic_exploration",
            "curiosity_research",
            "external_trend_watch",
            "idle_observation",
        ),
        DesireType.EXPRESSION: (
            "autonomous_talk",
            "directed_talk",
            "body_expression_loop",
        ),
        DesireType.RECOGNITION: (
            "stream_main_segment",
            "stream_comment_response",
        ),
        DesireType.AUTONOMY: (
            "autonomous_talk",
            "plugin_activity",
        ),
        DesireType.SECURITY: (
            "listening_mode",
            "idle_observation",
        ),
        DesireType.ACHIEVEMENT: (
            "topic_exploration",
            "plugin_activity",
            "stream_main_segment",
        ),
    }

    _STRATEGY_RECOMMENDATIONS: Mapping[DesireType, tuple[str, ...]] = {
        DesireType.CONNECTION: (
            "continue_conversation",
            "acknowledge_other",
            "ask_follow_up",
        ),
        DesireType.CURIOSITY: (
            "ask_for_detail",
            "explore_related_topic",
            "observe_before_speaking",
        ),
        DesireType.EXPRESSION: (
            "share_reaction",
            "self_disclose_briefly",
            "state_preference",
        ),
        DesireType.RECOGNITION: (
            "offer_help",
            "explain_clearly",
            "confirm_contribution",
        ),
        DesireType.AUTONOMY: (
            "propose_direction",
            "take_initiative",
            "state_choice",
        ),
        DesireType.SECURITY: (
            "set_boundary",
            "slow_down",
            "seek_clarification",
        ),
        DesireType.ACHIEVEMENT: (
            "define_next_step",
            "summarize_progress",
            "complete_current_goal",
        ),
    }

    _CONFLICT_PAIRS: tuple[tuple[DesireType, DesireType, str], ...] = (
        (
            DesireType.CONNECTION,
            DesireType.SECURITY,
            "connection_security_tension",
        ),
        (
            DesireType.EXPRESSION,
            DesireType.SECURITY,
            "expression_security_tension",
        ),
        (
            DesireType.CURIOSITY,
            DesireType.SECURITY,
            "curiosity_security_tension",
        ),
        (
            DesireType.AUTONOMY,
            DesireType.RECOGNITION,
            "autonomy_recognition_tension",
        ),
    )

    def __init__(
        self,
        *,
        top_count: int = 3,
        conflict_level_threshold: float = 0.55,
        conflict_intensity_threshold: float = 0.30,
        recommendation_limit: int = 5,
    ) -> None:
        if top_count < 1:
            raise ValueError("top_countは1以上にしてください。")
        if recommendation_limit < 1:
            raise ValueError("recommendation_limitは1以上にしてください。")
        self._top_count = top_count
        self._conflict_level_threshold = self._clamp_01(
            conflict_level_threshold
        )
        self._conflict_intensity_threshold = self._clamp_01(
            conflict_intensity_threshold
        )
        self._recommendation_limit = recommendation_limit

    def appraise(
        self,
        desire: DesireState,
        relationship: RelationshipState | None = None,
        *,
        moral_profile: MoralProfile | None = None,
        moral_state: MoralState | None = None,
    ) -> MotivationAppraisal:
        if (moral_profile is None) != (moral_state is None):
            raise ValueError("moral_profileとmoral_stateは同時に指定してください。")

        expression_strength = self._expression_strength(relationship)
        ordered_types = sorted(
            DesireType,
            key=lambda desire_type: (
                -desire.get(desire_type).effective_level,
                list(DesireType).index(desire_type),
            ),
        )
        ranked_desires = tuple(
            RankedDesire(
                desire_type=desire_type,
                rank=index,
                effective_level=desire.get(desire_type).effective_level,
                expressed_level=(
                    desire.get(desire_type).effective_level
                    * expression_strength
                ),
            )
            for index, desire_type in enumerate(
                ordered_types[: self._top_count],
                start=1,
            )
        )
        conflicts = self._conflicts(desire)
        top_types = tuple(item.desire_type for item in ranked_desires)
        activities = self._recommendations(
            top_types,
            self._ACTIVITY_RECOMMENDATIONS,
        )
        strategies = self._recommendations(
            top_types,
            self._STRATEGY_RECOMMENDATIONS,
        )
        moral_available = moral_profile is not None and moral_state is not None
        return MotivationAppraisal(
            ranked_desires=ranked_desires,
            conflicts=conflicts,
            expression_strength=expression_strength,
            recommended_activity_types=activities,
            recommended_conversation_strategies=strategies,
            moral_evaluation_available=moral_available,
            moral_observation_only=True,
            moral_profile=moral_profile,
            moral_state=moral_state,
            moral_composite=(
                moral_profile.compose(moral_state)
                if moral_profile is not None and moral_state is not None
                else None
            ),
            suppressed_activity_types=(),
            suppression_reasons=(
                ("moral_fit_observation_only",)
                if moral_available
                else ("moral_profile_not_available",)
            ),
        )

    def _conflicts(self, desire: DesireState) -> tuple[DesireConflict, ...]:
        conflicts: list[DesireConflict] = []
        for left_type, right_type, reason in self._CONFLICT_PAIRS:
            left_level = desire.get(left_type).effective_level
            right_level = desire.get(right_type).effective_level
            if (
                left_level < self._conflict_level_threshold
                or right_level < self._conflict_level_threshold
            ):
                continue
            closeness = 1.0 - abs(left_level - right_level)
            intensity = min(left_level, right_level) * closeness
            if intensity < self._conflict_intensity_threshold:
                continue
            conflicts.append(
                DesireConflict(
                    left=left_type,
                    right=right_type,
                    intensity=intensity,
                    reason=reason,
                )
            )
        return tuple(
            sorted(
                conflicts,
                key=lambda conflict: (
                    -conflict.intensity,
                    conflict.left.value,
                    conflict.right.value,
                ),
            )
        )

    def _recommendations(
        self,
        desire_types: Iterable[DesireType],
        mapping: Mapping[DesireType, tuple[str, ...]],
    ) -> tuple[str, ...]:
        result: list[str] = []
        for desire_type in desire_types:
            for candidate in mapping[desire_type]:
                if candidate not in result:
                    result.append(candidate)
                if len(result) >= self._recommendation_limit:
                    return tuple(result)
        return tuple(result)

    @classmethod
    def _expression_strength(
        cls,
        relationship: RelationshipState | None,
    ) -> float:
        if relationship is None:
            return 0.50
        normalized_affinity = (relationship.affinity + 1.0) / 2.0
        return cls._clamp_01(
            0.35
            + relationship.familiarity * 0.20
            + relationship.trust * 0.25
            + normalized_affinity * 0.20
        )

    @staticmethod
    def _clamp_01(value: float) -> float:
        return max(0.0, min(1.0, float(value)))
