from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from app.domain.morals.activity_candidate_application_condition import (
    MoralActivityCandidateApplicationCondition,
    MoralActivityCandidateApplicationConditionEvaluator,
)
from app.domain.morals.activity_candidate_execution_boundary_equivalence import (
    ActivityCandidateExecutionBoundaryEquivalenceAssessment,
)
from app.domain.morals.activity_candidate_fit import MoralActivityCandidateFit
from app.domain.morals.activity_candidate_semantic_equivalence import (
    ActivityCandidateSemanticEquivalenceAssessment,
    ActivityCandidateSemanticEquivalenceEvaluator,
    ActivityCandidateSemanticEquivalenceEvidence,
    SemanticEquivalenceStatus,
)
from app.shared.contracts.activity import ActivityDefinition


@dataclass(frozen=True, slots=True)
class MoralActivityCandidatePreferenceShadow:
    """Moral候補選好を実適用せず比較するための診断結果。"""

    mode: str = "shadow"
    static_eligible: bool = False
    activation_permitted: bool = False
    preferred_activity_type: str | None = None
    candidate_group: tuple[str, ...] = ()
    current_order: tuple[str, ...] = ()
    hypothetical_order: tuple[str, ...] = ()
    top_fit: float | None = None
    runner_up_fit: float | None = None
    fit_margin: float | None = None
    semantic_equivalence: ActivityCandidateSemanticEquivalenceAssessment = field(
        default_factory=ActivityCandidateSemanticEquivalenceAssessment
    )
    execution_boundary_equivalence: (
        ActivityCandidateExecutionBoundaryEquivalenceAssessment
    ) = field(
        default_factory=ActivityCandidateExecutionBoundaryEquivalenceAssessment
    )
    application_condition: MoralActivityCandidateApplicationCondition = field(
        default_factory=MoralActivityCandidateApplicationCondition
    )
    reasons: tuple[str, ...] = ()

    @property
    def semantic_equivalence_confirmed(self) -> bool:
        return self.semantic_equivalence.confirmed

    @property
    def execution_boundary_equivalence_confirmed(self) -> bool:
        return self.execution_boundary_equivalence.confirmed

    @property
    def application_condition_ready(self) -> bool:
        return self.application_condition.ready_for_limited_activation

    def as_context(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "static_eligible": self.static_eligible,
            "semantic_equivalence_confirmed": (
                self.semantic_equivalence_confirmed
            ),
            "execution_boundary_equivalence_confirmed": (
                self.execution_boundary_equivalence_confirmed
            ),
            "application_condition_ready": self.application_condition_ready,
            "activation_permitted": self.activation_permitted,
            "preferred_activity_type": self.preferred_activity_type,
            "candidate_group": list(self.candidate_group),
            "current_order": list(self.current_order),
            "hypothetical_order": list(self.hypothetical_order),
            "top_fit": self.top_fit,
            "runner_up_fit": self.runner_up_fit,
            "fit_margin": self.fit_margin,
            "semantic_equivalence": self.semantic_equivalence.as_context(),
            "execution_boundary_equivalence": (
                self.execution_boundary_equivalence.as_context()
            ),
            "application_condition": self.application_condition.as_context(),
            "reasons": list(self.reasons),
        }


class MoralActivityCandidatePreferenceShadowEvaluator:
    """将来のMoral補助選好条件を、現在順序を変えずに評価する。"""

    MINIMUM_TOP_FIT = 0.58
    MINIMUM_FIT_MARGIN = 0.08
    MAXIMUM_STABLE_AGGRESSIVE_IMPULSE = 0.80
    MAXIMUM_STABLE_SELFISH_IMPULSE = 0.80

    def __init__(
        self,
        semantic_equivalence_evaluator: (
            ActivityCandidateSemanticEquivalenceEvaluator | None
        ) = None,
        application_condition_evaluator: (
            MoralActivityCandidateApplicationConditionEvaluator | None
        ) = None,
    ) -> None:
        self._semantic_equivalence_evaluator = (
            semantic_equivalence_evaluator
            or ActivityCandidateSemanticEquivalenceEvaluator()
        )
        self._application_condition_evaluator = (
            application_condition_evaluator
            or MoralActivityCandidateApplicationConditionEvaluator()
        )

    def evaluate(
        self,
        definitions: Sequence[ActivityDefinition],
        fits: Sequence[MoralActivityCandidateFit],
        preference_contexts: Sequence[Mapping[str, object]],
        moral: Mapping[str, object] | None,
        semantic_equivalence_evidence: (
            ActivityCandidateSemanticEquivalenceEvidence | None
        ) = None,
    ) -> MoralActivityCandidatePreferenceShadow:
        current_order = tuple(
            definition.activity_type for definition in definitions
        )
        fit_by_activity = {fit.activity_type: fit for fit in fits}
        preference_by_activity = self._preference_by_activity(
            preference_contexts
        )
        blockers: list[str] = []

        self._append_moral_context_blockers(blockers, moral)

        candidate_group = self._select_candidate_group(
            current_order,
            fit_by_activity,
            preference_by_activity,
        )
        if len(candidate_group) < 2:
            self._append_once(
                blockers,
                "equivalent_motivation_group_unavailable",
            )

        semantic_equivalence = self._semantic_equivalence_evaluator.evaluate(
            candidate_group,
            semantic_equivalence_evidence,
        )

        top_activity: str | None = None
        top_fit: float | None = None
        runner_up_fit: float | None = None
        fit_margin: float | None = None
        ordered_group = candidate_group

        if len(candidate_group) >= 2:
            current_position = {
                activity_type: index
                for index, activity_type in enumerate(current_order)
            }
            ordered_group = tuple(
                sorted(
                    candidate_group,
                    key=lambda activity_type: (
                        -fit_by_activity[activity_type].moral_fit,
                        current_position[activity_type],
                    ),
                )
            )
            top_activity = ordered_group[0]
            top_fit = fit_by_activity[top_activity].moral_fit
            runner_up_fit = fit_by_activity[ordered_group[1]].moral_fit
            fit_margin = top_fit - runner_up_fit
            if top_fit < self.MINIMUM_TOP_FIT:
                self._append_once(blockers, "top_fit_below_threshold")
            if fit_margin < self.MINIMUM_FIT_MARGIN:
                self._append_once(blockers, "fit_margin_below_threshold")

        static_eligible = not blockers
        hypothetical_order = current_order
        preferred_activity_type: str | None = None
        if static_eligible and top_activity is not None:
            hypothetical_order = self._replace_group_order(
                current_order,
                candidate_group,
                ordered_group,
            )
            preferred_activity_type = top_activity

        execution_boundary_equivalence = (
            ActivityCandidateExecutionBoundaryEquivalenceAssessment()
        )
        application_condition = self._application_condition_evaluator.evaluate(
            static_eligible=static_eligible,
            candidate_group=candidate_group,
            preferred_activity_type=preferred_activity_type,
            semantic_equivalence=semantic_equivalence,
            execution_boundary_equivalence=execution_boundary_equivalence,
        )

        semantic_reason = (
            "semantic_equivalence_confirmed_but_activation_disabled"
            if semantic_equivalence.status
            is SemanticEquivalenceStatus.CONFIRMED
            else (
                "semantic_equivalence_rejected"
                if semantic_equivalence.status
                is SemanticEquivalenceStatus.REJECTED
                else "semantic_equivalence_unconfirmed"
            )
        )
        reasons = tuple(
            blockers
            + [
                semantic_reason,
                "shadow_mode_only",
            ]
        )
        return MoralActivityCandidatePreferenceShadow(
            static_eligible=static_eligible,
            activation_permitted=False,
            preferred_activity_type=preferred_activity_type,
            candidate_group=candidate_group,
            current_order=current_order,
            hypothetical_order=hypothetical_order,
            top_fit=top_fit,
            runner_up_fit=runner_up_fit,
            fit_margin=fit_margin,
            semantic_equivalence=semantic_equivalence,
            execution_boundary_equivalence=execution_boundary_equivalence,
            application_condition=application_condition,
            reasons=reasons,
        )

    def _append_moral_context_blockers(
        self,
        blockers: list[str],
        moral: Mapping[str, object] | None,
    ) -> None:
        if moral is None:
            self._append_once(blockers, "moral_context_unavailable")
            return
        if moral.get("observation_only") is not True:
            self._append_once(
                blockers,
                "moral_context_not_observation_only",
            )
        state = moral.get("state")
        if not isinstance(state, Mapping):
            self._append_once(blockers, "moral_context_unavailable")
            return
        aggressive_impulse = self._float_or_none(
            state.get("aggressive_impulse")
        )
        selfish_impulse = self._float_or_none(state.get("selfish_impulse"))
        if aggressive_impulse is None or selfish_impulse is None:
            self._append_once(blockers, "moral_context_unavailable")
            return
        if (
            aggressive_impulse
            >= self.MAXIMUM_STABLE_AGGRESSIVE_IMPULSE
            or selfish_impulse >= self.MAXIMUM_STABLE_SELFISH_IMPULSE
        ):
            self._append_once(blockers, "moral_state_unstable")

    @classmethod
    def _select_candidate_group(
        cls,
        current_order: Sequence[str],
        fit_by_activity: Mapping[str, MoralActivityCandidateFit],
        preference_by_activity: Mapping[str, Mapping[str, object]],
    ) -> tuple[str, ...]:
        groups: dict[float, list[str]] = {}
        for activity_type in current_order:
            fit = fit_by_activity.get(activity_type)
            preference = preference_by_activity.get(activity_type)
            if fit is None or preference is None:
                continue
            if not fit.profiled or preference.get("pinned") is True:
                continue
            motivation_score = cls._float_or_none(
                preference.get("motivation_score")
            )
            if motivation_score is None:
                continue
            groups.setdefault(round(motivation_score, 12), []).append(
                activity_type
            )

        candidates = [
            (score, tuple(activity_types))
            for score, activity_types in groups.items()
            if len(activity_types) >= 2
        ]
        if not candidates:
            return ()
        order_index = {
            activity_type: index
            for index, activity_type in enumerate(current_order)
        }
        _, selected = min(
            candidates,
            key=lambda item: (
                -item[0],
                min(order_index[activity_type] for activity_type in item[1]),
            ),
        )
        return selected

    @staticmethod
    def _replace_group_order(
        current_order: tuple[str, ...],
        candidate_group: Sequence[str],
        ordered_group: Sequence[str],
    ) -> tuple[str, ...]:
        candidate_set = set(candidate_group)
        result = list(current_order)
        positions = [
            index
            for index, activity_type in enumerate(current_order)
            if activity_type in candidate_set
        ]
        for index, activity_type in zip(positions, ordered_group):
            result[index] = activity_type
        return tuple(result)

    @staticmethod
    def _preference_by_activity(
        preference_contexts: Sequence[Mapping[str, object]],
    ) -> dict[str, Mapping[str, object]]:
        result: dict[str, Mapping[str, object]] = {}
        for preference in preference_contexts:
            activity_type = preference.get("activity_type")
            if not isinstance(activity_type, str):
                continue
            normalized = activity_type.strip()
            if not normalized:
                continue
            result[normalized] = preference
        return result

    @staticmethod
    def _float_or_none(value: object) -> float | None:
        if isinstance(value, bool):
            return None
        if not isinstance(value, (int, float)):
            return None
        return float(value)

    @staticmethod
    def _append_once(values: list[str], value: str) -> None:
        if value not in values:
            values.append(value)
