from __future__ import annotations

from dataclasses import replace
from enum import Enum
from typing import Protocol

from app.domain.brain_operational_bounds import BrainOperationalBoundsPolicy
from app.domain.contracts import CapabilityDescriptor, CapabilityRequirement

from .contracts import (
    DeterministicPlanningDirective,
    GoalPlanningCandidate,
    GoalPlanningContextSnapshot,
)


class PlanningBoundsFailureCode(str, Enum):
    CONTEXT_TOO_LARGE = "planning_context_too_large"
    PLAN_TOO_LARGE = "plan_too_large"
    POLICY_STALE = "planning_policy_stale"


class GoalPlanningBoundsError(ValueError):
    def __init__(self, code: PlanningBoundsFailureCode, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code.value}: {detail}")


class GoalPlanningBoundsPolicyPort(Protocol):
    async def current_policy(
        self, snapshot: GoalPlanningContextSnapshot
    ) -> BrainOperationalBoundsPolicy: ...


def _require_policy(bounds_policy: BrainOperationalBoundsPolicy) -> BrainOperationalBoundsPolicy:
    if not isinstance(bounds_policy, BrainOperationalBoundsPolicy):
        raise ValueError("容量方針はBrainOperationalBoundsPolicyでなければなりません")
    return bounds_policy


def _is_requirement_relevant(
    descriptor: CapabilityDescriptor,
    requirement: CapabilityRequirement,
) -> bool:
    return (
        descriptor.capability_type == requirement.capability_type
        and requirement.operation in descriptor.operations
    )


def assert_planning_policy_generation(
    snapshot: GoalPlanningContextSnapshot,
    bounds_policy: BrainOperationalBoundsPolicy,
) -> None:
    policy = _require_policy(bounds_policy)
    if (
        snapshot.goal_context.policy_id != policy.policy_id
        or snapshot.goal_context.policy_revision != policy.policy_revision
    ):
        raise GoalPlanningBoundsError(
            PlanningBoundsFailureCode.POLICY_STALE,
            "Planning Snapshotとcurrent policy generationが一致しません",
        )


def validate_planning_context_bounds(
    snapshot: GoalPlanningContextSnapshot,
    bounds_policy: BrainOperationalBoundsPolicy,
) -> None:
    if not isinstance(snapshot, GoalPlanningContextSnapshot):
        raise ValueError("snapshotはGoalPlanningContextSnapshotでなければなりません")
    bounds = _require_policy(bounds_policy).planning
    checks = (
        ("capability_descriptors", len(snapshot.capabilities), bounds.max_capability_descriptors),
        ("planning_blockers", len(snapshot.planning_blockers), bounds.max_planning_blockers),
        ("activity_context_refs", len(snapshot.activities), bounds.max_activity_context_refs),
    )
    for name, actual, maximum in checks:
        if actual > maximum:
            raise GoalPlanningBoundsError(
                PlanningBoundsFailureCode.CONTEXT_TOO_LARGE,
                f"{name} count={actual} limit={maximum}",
            )


def build_bounded_goal_planning_context(
    snapshot: GoalPlanningContextSnapshot,
    bounds_policy: BrainOperationalBoundsPolicy,
) -> GoalPlanningContextSnapshot:
    if not isinstance(snapshot, GoalPlanningContextSnapshot):
        raise ValueError("snapshotはGoalPlanningContextSnapshotでなければなりません")
    policy = _require_policy(bounds_policy)
    assert_planning_policy_generation(snapshot, policy)
    bounds = policy.planning
    blockers = snapshot.planning_blockers
    activities = snapshot.activities
    if len(blockers) > bounds.max_planning_blockers:
        raise GoalPlanningBoundsError(
            PlanningBoundsFailureCode.CONTEXT_TOO_LARGE,
            f"planning_blockers count={len(blockers)} limit={bounds.max_planning_blockers}",
        )
    if len(activities) > bounds.max_activity_context_refs:
        raise GoalPlanningBoundsError(
            PlanningBoundsFailureCode.CONTEXT_TOO_LARGE,
            f"activity_context_refs count={len(activities)} limit={bounds.max_activity_context_refs}",
        )

    capability_values = snapshot.capabilities
    activity_capability_ids = {
        item.capability_id for item in activities if item.capability_id is not None
    }
    required_capability_ids = set(activity_capability_ids)
    required_capability_ids.update(
        descriptor.capability_id
        for descriptor in capability_values
        if any(
            _is_requirement_relevant(descriptor, requirement)
            for requirement in snapshot.planning_requirements
        )
    )
    required = tuple(
        descriptor
        for descriptor in capability_values
        if descriptor.capability_id in required_capability_ids
    )
    if len(required) > bounds.max_capability_descriptors:
        raise GoalPlanningBoundsError(
            PlanningBoundsFailureCode.CONTEXT_TOO_LARGE,
            "required capability descriptors exceed planning capacity",
        )
    remaining = sorted(
        (
            descriptor
            for descriptor in capability_values
            if descriptor.capability_id not in required_capability_ids
        ),
        key=lambda item: (item.capability_type, item.capability_id, -item.revision),
    )
    selected = required + tuple(
        remaining[: bounds.max_capability_descriptors - len(required)]
    )
    bounded = replace(snapshot, capabilities=selected)
    validate_planning_context_bounds(bounded, policy)
    return bounded


def validate_plan_bounds(
    value: GoalPlanningCandidate | DeterministicPlanningDirective,
    bounds_policy: BrainOperationalBoundsPolicy,
) -> None:
    if not isinstance(value, (GoalPlanningCandidate, DeterministicPlanningDirective)):
        raise ValueError("planning valueの型が不正です")
    bounds = _require_policy(bounds_policy).planning
    if len(value.steps) > bounds.max_plan_steps:
        raise GoalPlanningBoundsError(
            PlanningBoundsFailureCode.PLAN_TOO_LARGE,
            f"steps count={len(value.steps)} limit={bounds.max_plan_steps}",
        )
    for step in value.steps:
        checks = (
            (
                "dependency_step_ids",
                len(step.dependency_step_ids),
                bounds.max_dependencies_per_step,
            ),
            ("precondition_ids", len(step.precondition_ids), bounds.max_precondition_refs_per_step),
            (
                "completion_condition_refs",
                len(step.completion_condition_refs),
                bounds.max_completion_refs_per_step,
            ),
        )
        for name, actual, maximum in checks:
            if actual > maximum:
                raise GoalPlanningBoundsError(
                    PlanningBoundsFailureCode.PLAN_TOO_LARGE,
                    f"step={step.step_id} {name} count={actual} limit={maximum}",
                )
    if len(value.completion_condition_refs) > bounds.max_plan_completion_refs:
        raise GoalPlanningBoundsError(
            PlanningBoundsFailureCode.PLAN_TOO_LARGE,
            "plan completion refs exceed planning capacity",
        )
    if len(value.checkpoint_step_ids) > bounds.max_checkpoint_refs:
        raise GoalPlanningBoundsError(
            PlanningBoundsFailureCode.PLAN_TOO_LARGE,
            "checkpoint refs exceed planning capacity",
        )
