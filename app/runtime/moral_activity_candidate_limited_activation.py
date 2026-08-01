from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field, replace

from app.domain.behavior import (
    ActivityOperation,
    BehaviorPlanningContext,
    SituationAnalysis,
)
from app.domain.morals import MoralActivityCandidatePreferenceShadow
from app.utils.trace import TraceLogger


@dataclass(frozen=True, slots=True)
class MoralActivityCandidateLimitedActivationPolicy:
    """Moral候補選好を実適用できる範囲を明示する機能フラグ。"""

    enabled: bool = False
    allowlisted_activity_types: frozenset[str] = field(default_factory=frozenset)

    ENV_ENABLED = "YURA_MORAL_CANDIDATE_LIMITED_ACTIVATION_ENABLED"
    ENV_ALLOWLIST = "YURA_MORAL_CANDIDATE_LIMITED_ACTIVATION_ALLOWLIST"

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be bool")
        normalized: set[str] = set()
        for activity_type in self.allowlisted_activity_types:
            if not isinstance(activity_type, str):
                raise TypeError("allowlisted_activity_types must contain str")
            value = activity_type.strip()
            if not value:
                raise ValueError("allowlisted_activity_types must not contain blanks")
            normalized.add(value)
        object.__setattr__(self, "allowlisted_activity_types", frozenset(normalized))

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> MoralActivityCandidateLimitedActivationPolicy:
        values = os.environ if environment is None else environment
        raw_enabled = values.get(cls.ENV_ENABLED, "0").strip().lower()
        true_values = {"1", "true", "yes", "on"}
        false_values = {"0", "false", "no", "off", ""}
        if raw_enabled in true_values:
            enabled = True
        elif raw_enabled in false_values:
            enabled = False
        else:
            raise ValueError(
                f"{cls.ENV_ENABLED} must be one of "
                "1,true,yes,on,0,false,no,off"
            )
        allowlist = frozenset(
            item.strip()
            for item in values.get(cls.ENV_ALLOWLIST, "").split(",")
            if item.strip()
        )
        return cls(
            enabled=enabled,
            allowlisted_activity_types=allowlist,
        )


@dataclass(frozen=True, slots=True)
class MoralActivityCandidateLimitedActivationDecision:
    """限定適用Gateの判定結果。"""

    applied: bool
    reason: str
    original_activity_type: str | None
    selected_activity_type: str | None
    candidate_group: tuple[str, ...] = ()
    policy_enabled: bool = False
    allowlisted_activity_types: tuple[str, ...] = ()

    def as_context(self) -> dict[str, object]:
        return {
            "applied": self.applied,
            "reason": self.reason,
            "original_activity_type": self.original_activity_type,
            "selected_activity_type": self.selected_activity_type,
            "candidate_group": list(self.candidate_group),
            "policy_enabled": self.policy_enabled,
            "allowlisted_activity_types": list(self.allowlisted_activity_types),
        }


class MoralActivityCandidateLimitedActivationApplier:
    """確認済みの同等候補に限り、LLM候補をMoral推奨候補へ差し替える。"""

    def __init__(
        self,
        policy: MoralActivityCandidateLimitedActivationPolicy | None = None,
        *,
        trace_logger: TraceLogger | None = None,
    ) -> None:
        self._policy = policy or MoralActivityCandidateLimitedActivationPolicy()
        self._trace_logger = trace_logger or TraceLogger()

    @property
    def policy(self) -> MoralActivityCandidateLimitedActivationPolicy:
        return self._policy

    def apply(
        self,
        context: BehaviorPlanningContext,
        analysis: SituationAnalysis,
        shadow: MoralActivityCandidatePreferenceShadow | None,
    ) -> tuple[SituationAnalysis, MoralActivityCandidateLimitedActivationDecision]:
        reason = self._block_reason(context, analysis, shadow)
        original = analysis.activity_candidate
        selected = original
        applied = False
        candidate_group = (
            shadow.application_condition.candidate_group if shadow is not None else ()
        )

        if reason is None and shadow is not None:
            preferred = shadow.application_condition.preferred_activity_type
            if preferred == original:
                reason = "preferred_activity_already_selected"
            else:
                selected = preferred
                analysis = replace(analysis, activity_candidate=preferred)
                applied = True
                reason = "moral_candidate_limited_activation_applied"

        decision = MoralActivityCandidateLimitedActivationDecision(
            applied=applied,
            reason=reason or "limited_activation_not_applied",
            original_activity_type=original,
            selected_activity_type=selected,
            candidate_group=candidate_group,
            policy_enabled=self._policy.enabled,
            allowlisted_activity_types=tuple(
                sorted(self._policy.allowlisted_activity_types)
            ),
        )
        self._trace_logger.debug(
            "moral_candidate_limited_activation:evaluated",
            source_event_id=context.source_event_id,
            evaluator_type=analysis.evaluator_type,
            operation=(analysis.operation.value if analysis.operation else None),
            application_condition_status=(
                shadow.application_condition.status.value if shadow is not None else None
            ),
            application_condition_ready=(
                shadow.application_condition.ready_for_limited_activation
                if shadow is not None
                else False
            ),
            **decision.as_context(),
        )
        return analysis, decision

    def _block_reason(
        self,
        context: BehaviorPlanningContext,
        analysis: SituationAnalysis,
        shadow: MoralActivityCandidatePreferenceShadow | None,
    ) -> str | None:
        if not self._policy.enabled:
            return "limited_activation_feature_disabled"
        if shadow is None:
            return "limited_activation_shadow_unavailable"
        condition = shadow.application_condition
        if not condition.ready_for_limited_activation:
            return "limited_activation_condition_not_ready"
        if analysis.evaluator_type != "llm":
            return "limited_activation_evaluator_not_eligible"
        if analysis.operation is not ActivityOperation.START:
            return "limited_activation_operation_not_start"
        if (
            context.active_activity_definition is not None
            or context.ongoing_activity_type is not None
            or context.ongoing_activity is not None
        ):
            return "limited_activation_active_or_ongoing_activity_present"

        candidate_group = condition.candidate_group
        preferred = condition.preferred_activity_type
        if analysis.activity_candidate not in candidate_group:
            return "limited_activation_selected_candidate_outside_group"
        if preferred not in candidate_group:
            return "limited_activation_preferred_candidate_outside_group"
        if not set(candidate_group).issubset(
            self._policy.allowlisted_activity_types
        ):
            return "limited_activation_candidate_group_not_allowlisted"

        definition_by_activity = {
            definition.activity_type: definition
            for definition in context.activity_definitions
        }
        if any(
            activity_type not in definition_by_activity
            for activity_type in candidate_group
        ):
            return "limited_activation_candidate_definition_missing"
        preferred_definition = definition_by_activity[preferred]
        if analysis.operation not in preferred_definition.supported_operations:
            return "limited_activation_operation_not_supported"
        return None
