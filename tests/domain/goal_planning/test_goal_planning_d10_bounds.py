import asyncio
from dataclasses import replace
from typing import cast

import pytest

from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
from app.domain.contracts import CapabilityAvailability, CapabilityDescriptor, ExecutionStatus
from app.domain.goal_planning import (
    ActivityContextRef,
    ActivityPlanStep,
    GoalPlanner,
    GoalPlanningAuthority,
    GoalPlanningBoundsError,
    GoalPlanningPolicy,
    PlanningBlocker,
    PlanningBlockerKind,
    PlanningBoundsFailureCode,
    build_bounded_goal_planning_context,
    build_request,
    parse_candidate,
    validate_plan_bounds,
)
from app.domain.goals import InterruptionPolicy
from tests.domain.goal_planning.test_goal_planning import (
    DelayedPort,
    FakeLiveState,
    NOW,
    candidate,
    candidate_json,
    context,
    policy,
    step,
)


def canonical_context(*, deterministic: bool = False):  # type: ignore[no-untyped-def]
    item = context(deterministic=deterministic)
    return replace(
        item,
        goal_context=replace(
            item.goal_context,
            policy_id=V2_BRAIN_OPERATIONAL_BOUNDS_POLICY.policy_id,
            policy_revision=V2_BRAIN_OPERATIONAL_BOUNDS_POLICY.policy_revision,
        ),
    )


def planning_policy(**changes: int):  # type: ignore[no-untyped-def]
    return replace(
        V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
        planning=replace(V2_BRAIN_OPERATIONAL_BOUNDS_POLICY.planning, **changes),
    )


def descriptor(
    capability_id: str,
    capability_type: str,
    operation: str,
) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability_id,
        capability_type,
        (operation,),
        CapabilityAvailability.AVAILABLE,
        1,
        {},
    )


def test_bounded_context_keeps_required_capability_then_stable_remaining() -> None:
    item = canonical_context()
    raw = replace(
        item,
        capabilities=(
            descriptor("cap-z-required", "research", "collect"),
            descriptor("cap-b", "beta", "noop"),
            descriptor("cap-a", "alpha", "noop"),
        ),
    )
    bounded = build_bounded_goal_planning_context(
        raw,
        planning_policy(max_capability_descriptors=2),
    )
    assert [item.capability_id for item in bounded.capabilities] == [
        "cap-z-required",
        "cap-a",
    ]
    assert len(raw.capabilities) == 3


def test_required_capability_overflow_fails_closed_without_truncation() -> None:
    item = canonical_context()
    raw = replace(
        item,
        capabilities=(
            descriptor("cap-required-a", "research", "collect"),
            descriptor("cap-required-b", "research", "collect"),
        ),
    )
    with pytest.raises(GoalPlanningBoundsError) as error:
        build_bounded_goal_planning_context(
            raw,
            planning_policy(max_capability_descriptors=1),
        )
    assert error.value.code is PlanningBoundsFailureCode.CONTEXT_TOO_LARGE
    assert len(raw.capabilities) == 2


def test_blocker_and_activity_context_overflow_fail_closed() -> None:
    blockers = (
        PlanningBlocker("blocker-a", PlanningBlockerKind.CONSTRAINT_CONFLICT, "constraint-a"),
        PlanningBlocker("blocker-b", PlanningBlockerKind.CONSTRAINT_CONFLICT, "constraint-b"),
    )
    with pytest.raises(GoalPlanningBoundsError) as blocker_error:
        build_bounded_goal_planning_context(
            replace(canonical_context(), planning_blockers=blockers),
            planning_policy(max_planning_blockers=1),
        )
    assert blocker_error.value.code is PlanningBoundsFailureCode.CONTEXT_TOO_LARGE

    activities = (
        ActivityContextRef("activity-a", "goal-1", "collect", ExecutionStatus.STARTED),
        ActivityContextRef("activity-b", "goal-1", "collect", ExecutionStatus.STARTED),
    )
    with pytest.raises(GoalPlanningBoundsError) as activity_error:
        build_bounded_goal_planning_context(
            replace(canonical_context(), activities=activities),
            planning_policy(max_activity_context_refs=1),
        )
    assert activity_error.value.code is PlanningBoundsFailureCode.CONTEXT_TOO_LARGE


def test_build_request_rejects_unbounded_context() -> None:
    item = replace(
        canonical_context(),
        capabilities=(
            descriptor("cap-required", "research", "collect"),
            descriptor("cap-extra", "extra", "noop"),
        ),
    )
    limited = planning_policy(max_capability_descriptors=1)
    goal_policy = replace(policy(), bounds_policy=limited)
    with pytest.raises(GoalPlanningBoundsError) as error:
        build_request(
            item,
            request_id="request-overflow",
            trace_id="trace-overflow",
            created_at=NOW,
            policy=goal_policy,
        )
    assert error.value.code is PlanningBoundsFailureCode.CONTEXT_TOO_LARGE


def plan_with_steps(count: int):  # type: ignore[no-untyped-def]
    steps = tuple(replace(step(), step_id=f"step-{index}") for index in range(count))
    return replace(candidate(), steps=steps, checkpoint_step_ids=())


@pytest.mark.parametrize("count", [64, 65])
def test_plan_step_64_65_boundary(count: int) -> None:
    value = plan_with_steps(count)
    if count == 64:
        validate_plan_bounds(value, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)
    else:
        with pytest.raises(GoalPlanningBoundsError) as error:
            validate_plan_bounds(value, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)
        assert error.value.code is PlanningBoundsFailureCode.PLAN_TOO_LARGE


@pytest.mark.parametrize("dependency_count", [16, 17])
def test_dependency_16_17_boundary(dependency_count: int) -> None:
    leaves = tuple(
        replace(step(), step_id=f"leaf-{index}") for index in range(dependency_count)
    )
    final = replace(
        step(),
        step_id="final",
        dependency_step_ids=tuple(item.step_id for item in leaves),
    )
    value = replace(candidate(), steps=leaves + (final,), checkpoint_step_ids=())
    if dependency_count == 16:
        validate_plan_bounds(value, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)
    else:
        with pytest.raises(GoalPlanningBoundsError):
            validate_plan_bounds(value, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)


@pytest.mark.parametrize(
    ("field_name", "equal_count", "above_count"),
    [
        ("precondition_ids", 32, 33),
        ("completion_condition_refs", 32, 33),
    ],
)
def test_step_reference_boundaries(
    field_name: str,
    equal_count: int,
    above_count: int,
) -> None:
    equal_step = replace(
        step(),
        **{field_name: tuple(f"ref-{index}" for index in range(equal_count))},
    )
    validate_plan_bounds(
        replace(candidate(), steps=(equal_step,), checkpoint_step_ids=()),
        V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
    )
    above_step = replace(
        step(),
        **{field_name: tuple(f"ref-{index}" for index in range(above_count))},
    )
    with pytest.raises(GoalPlanningBoundsError):
        validate_plan_bounds(
            replace(candidate(), steps=(above_step,), checkpoint_step_ids=()),
            V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
        )


@pytest.mark.parametrize("count", [64, 65])
def test_plan_completion_64_65_boundary(count: int) -> None:
    value = replace(
        candidate(),
        completion_condition_refs=tuple(f"completion-{index}" for index in range(count)),
        checkpoint_step_ids=(),
    )
    if count == 64:
        validate_plan_bounds(value, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)
    else:
        with pytest.raises(GoalPlanningBoundsError):
            validate_plan_bounds(value, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)


@pytest.mark.parametrize("count", [64, 65])
def test_checkpoint_64_65_boundary(count: int) -> None:
    steps = tuple(replace(step(), step_id=f"step-{index}") for index in range(count))
    value = replace(
        candidate(),
        steps=steps,
        checkpoint_step_ids=tuple(item.step_id for item in steps),
    )
    if count == 64:
        validate_plan_bounds(value, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)
    else:
        with pytest.raises(GoalPlanningBoundsError):
            validate_plan_bounds(value, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)


def test_retry_limit_rejects_bool() -> None:
    with pytest.raises(ValueError, match="retry_limit"):
        ActivityPlanStep(
            "step-bool-retry",
            "research",
            "collect",
            "target-1",
            None,
            (),
            (),
            (),
            (),
            InterruptionPolicy.RESUMABLE,
            cast(int, True),
            False,
        )


def test_parser_rejects_oversized_candidate_without_first_n_acceptance() -> None:
    value = candidate_json()
    source_step = cast(list[dict[str, object]], value["steps"])[0]
    value["steps"] = [
        {**source_step, "step_id": f"step-{index}"}
        for index in range(65)
    ]
    value["checkpoint_step_ids"] = []
    with pytest.raises(GoalPlanningBoundsError) as error:
        parse_candidate(
            value,
            created_at=NOW,
            bounds_policy=V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
        )
    assert error.value.code is PlanningBoundsFailureCode.PLAN_TOO_LARGE


class MutableBoundsPolicyState:
    def __init__(self) -> None:
        self.current = V2_BRAIN_OPERATIONAL_BOUNDS_POLICY

    async def current_policy(self, snapshot):  # type: ignore[no-untyped-def]
        return self.current


@pytest.mark.asyncio
async def test_late_llm_result_is_rejected_after_policy_revision_change() -> None:
    gate = asyncio.Event()
    bounds_state = MutableBoundsPolicyState()
    planner = GoalPlanner(
        DelayedPort(gate),
        FakeLiveState(),
        GoalPlanningAuthority(),
        policy(),
        bounds_state,
    )
    task = asyncio.create_task(
        planner.plan(
            canonical_context(),
            request_id="request-policy-stale",
            trace_id="trace-policy-stale",
            candidate_id="candidate-unused",
            plan_id="plan-policy-stale",
            created_at=NOW,
        )
    )
    await asyncio.sleep(0)
    bounds_state.current = replace(
        V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
        policy_revision=V2_BRAIN_OPERATIONAL_BOUNDS_POLICY.policy_revision + 1,
    )
    gate.set()
    with pytest.raises(GoalPlanningBoundsError) as error:
        await task
    assert error.value.code is PlanningBoundsFailureCode.POLICY_STALE
