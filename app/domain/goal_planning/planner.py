from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol, TypeVar, cast

from app.domain.brain_operational_bounds import (
    V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
    BrainOperationalBoundsPolicy,
)
from app.domain.contracts import CapabilityRequirement, RevisionVector
from app.domain.contracts.common import JsonValue, freeze_json, require_aware, utc_instant
from app.domain.goals import InterruptionPolicy
from app.domain.llm import (
    LLMActivationPolicy,
    LLMExecutionPolicy,
    LLMFailurePolicy,
    LLMInterruptibility,
    LLMPriority,
    LLMRoleDescriptor,
    LLMRoleRequest,
    LLMRoleResult,
    LLMRoleStatus,
    LLMStalePolicy,
    StructuredPayload,
    validate_role_exchange,
)
from app.usecases.ports.llm import LLMRolePort

from .authority import GoalPlanningAuthority
from .bounds import (
    GoalPlanningBoundsPolicyPort,
    assert_planning_policy_generation,
    validate_plan_bounds,
    validate_planning_context_bounds,
)
from .contracts import (
    ActivityPlan,
    ActivityPlanStep,
    DeterministicPlanningDirective,
    GoalPlanningCandidate,
    GoalPlanningCommitState,
    GoalPlanningContextSnapshot,
    GoalPlanningOutcome,
    PlanFailurePolicy,
)

ROLE_ID = "goal_planning"
INPUT_SCHEMA = "yura.goal-planning.context.v1"
OUTPUT_SCHEMA = "yura.goal-planning.candidate.v1"


@dataclass(frozen=True, slots=True)
class GoalPlanningPolicy:
    execution: LLMExecutionPolicy
    bounds_policy: BrainOperationalBoundsPolicy = V2_BRAIN_OPERATIONAL_BOUNDS_POLICY

    def __post_init__(self) -> None:
        if not isinstance(self.execution, LLMExecutionPolicy):
            raise ValueError("execution must be LLMExecutionPolicy")
        if not isinstance(self.bounds_policy, BrainOperationalBoundsPolicy):
            raise ValueError("bounds_policyはBrainOperationalBoundsPolicyでなければなりません")


class GoalPlanningLiveStatePort(Protocol):
    async def current_state(
        self, snapshot: GoalPlanningContextSnapshot
    ) -> GoalPlanningCommitState: ...


def descriptor(policy: GoalPlanningPolicy) -> LLMRoleDescriptor:
    return LLMRoleDescriptor(
        ROLE_ID,
        "active Goalをbounded ActivityPlan candidateへ分解する",
        INPUT_SCHEMA,
        OUTPUT_SCHEMA,
        "goal_planning_candidate_only",
        LLMActivationPolicy.CONDITIONAL,
        LLMFailurePolicy.FAIL_CLOSED,
        policy.execution,
    )


def build_request(
    snapshot: GoalPlanningContextSnapshot,
    *,
    request_id: str,
    trace_id: str,
    created_at: datetime,
    policy: GoalPlanningPolicy,
) -> LLMRoleRequest:
    if not isinstance(snapshot, GoalPlanningContextSnapshot):
        raise ValueError("snapshot must be GoalPlanningContextSnapshot")
    validate_planning_context_bounds(snapshot, policy.bounds_policy)
    require_aware(created_at, "created_at")
    if utc_instant(created_at) < utc_instant(snapshot.captured_at):
        raise ValueError("request cannot predate planning snapshot")
    return LLMRoleRequest(
        request_id,
        ROLE_ID,
        StructuredPayload(INPUT_SCHEMA, cast(JsonValue, snapshot.to_dict())),
        snapshot.source_event_ids,
        snapshot.revisions,
        (),
        LLMPriority.NORMAL,
        LLMInterruptibility.INTERRUPTIBLE,
        LLMStalePolicy.REJECT,
        policy.execution,
        created_at,
        trace_id,
    )


def candidate_from_directive(
    snapshot: GoalPlanningContextSnapshot,
    directive: DeterministicPlanningDirective,
    *,
    candidate_id: str,
    created_at: datetime,
    bounds_policy: BrainOperationalBoundsPolicy = V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
) -> GoalPlanningCandidate:
    if snapshot.deterministic_directive != directive:
        raise ValueError("directive does not match planning snapshot")
    validate_planning_context_bounds(snapshot, bounds_policy)
    validate_plan_bounds(directive, bounds_policy)
    return GoalPlanningCandidate(
        candidate_id,
        snapshot.goal.goal_id,
        snapshot.goal.revision,
        snapshot.source_event_ids,
        snapshot.revisions,
        directive.outcome,
        directive.steps,
        directive.completion_condition_refs,
        directive.checkpoint_step_ids,
        directive.failure_policy,
        directive.unmet_capabilities,
        created_at,
        directive.impossibility_blocker_ids,
    )


def commit_result(
    request: LLMRoleRequest,
    result: LLMRoleResult,
    *,
    snapshot: GoalPlanningContextSnapshot,
    current: GoalPlanningCommitState,
    authority: GoalPlanningAuthority,
    plan_id: str,
    policy: GoalPlanningPolicy,
) -> ActivityPlan:
    validate_planning_context_bounds(snapshot, policy.bounds_policy)
    failure = validate_role_exchange(descriptor(policy), request, result)
    if failure is not None:
        raise ValueError(failure.code.value)
    if result.status is not LLMRoleStatus.SUCCEEDED or result.output is None:
        raise ValueError("goal planning result is not committable")
    if request.input.value != freeze_json(snapshot.to_dict()):
        raise ValueError("planning snapshot does not match request")
    if request.source_event_ids != snapshot.source_event_ids:
        raise ValueError("request source events do not match planning snapshot")
    if request.revisions != snapshot.revisions:
        raise ValueError("request revisions do not match planning snapshot")
    return authority.commit(
        parse_candidate(
            result.output.value,
            created_at=result.completed_at,
            bounds_policy=policy.bounds_policy,
        ),
        snapshot,
        current,
        plan_id=plan_id,
        committed_at=result.completed_at,
        bounds_policy=policy.bounds_policy,
    )


class GoalPlanner:
    def __init__(
        self,
        port: LLMRolePort,
        live_state: GoalPlanningLiveStatePort,
        authority: GoalPlanningAuthority,
        policy: GoalPlanningPolicy,
        bounds_policy_state: GoalPlanningBoundsPolicyPort | None = None,
    ) -> None:
        self._port = port
        self._live_state = live_state
        self._authority = authority
        self._policy = policy
        self._bounds_policy_state = bounds_policy_state

    async def _validate_current_policy(self, snapshot: GoalPlanningContextSnapshot) -> None:
        if self._bounds_policy_state is None:
            return
        current_policy = await self._bounds_policy_state.current_policy(snapshot)
        assert_planning_policy_generation(snapshot, current_policy)

    async def plan(
        self,
        snapshot: GoalPlanningContextSnapshot,
        *,
        request_id: str,
        trace_id: str,
        candidate_id: str,
        plan_id: str,
        created_at: datetime,
    ) -> ActivityPlan:
        validate_planning_context_bounds(snapshot, self._policy.bounds_policy)
        directive = snapshot.deterministic_directive
        if directive is not None:
            candidate = candidate_from_directive(
                snapshot,
                directive,
                candidate_id=candidate_id,
                created_at=created_at,
                bounds_policy=self._policy.bounds_policy,
            )
            current = await self._live_state.current_state(snapshot)
            await self._validate_current_policy(snapshot)
            return self._authority.commit(
                candidate,
                snapshot,
                current,
                plan_id=plan_id,
                committed_at=created_at,
                bounds_policy=self._policy.bounds_policy,
            )
        request = build_request(
            snapshot,
            request_id=request_id,
            trace_id=trace_id,
            created_at=created_at,
            policy=self._policy,
        )
        result = await self._port.invoke(request)
        current = await self._live_state.current_state(snapshot)
        await self._validate_current_policy(snapshot)
        return commit_result(
            request,
            result,
            snapshot=snapshot,
            current=current,
            authority=self._authority,
            plan_id=plan_id,
            policy=self._policy,
        )


E = TypeVar("E", bound=Enum)


def parse_candidate(
    value: object,
    *,
    created_at: datetime,
    bounds_policy: BrainOperationalBoundsPolicy = V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
) -> GoalPlanningCandidate:
    item = _mapping(value, "goal planning candidate")
    required = {
        "candidate_id",
        "goal_id",
        "goal_state_revision",
        "source_event_ids",
        "revisions",
        "outcome",
        "steps",
        "completion_condition_refs",
        "checkpoint_step_ids",
        "failure_policy",
        "unmet_capabilities",
        "impossibility_blocker_ids",
    }
    if set(item) != required:
        raise ValueError("goal planning candidate fields do not match schema")
    revisions = _mapping(item["revisions"], "revisions")
    if set(revisions) != {
        "source_context_revision",
        "goal_revision",
        "attention_revision",
    }:
        raise ValueError("revision fields do not match schema")
    candidate = GoalPlanningCandidate(
        _string(item["candidate_id"], "candidate_id"),
        _string(item["goal_id"], "goal_id"),
        _revision(item["goal_state_revision"], "goal_state_revision"),
        _strings(item["source_event_ids"], "source_event_ids"),
        RevisionVector(
            _revision(revisions["source_context_revision"], "source_context_revision"),
            _revision(revisions["goal_revision"], "goal_revision"),
            _revision(revisions["attention_revision"], "attention_revision"),
        ),
        _enum(GoalPlanningOutcome, item["outcome"], "outcome"),
        tuple(_step(value) for value in _array(item["steps"], "steps")),
        _strings(item["completion_condition_refs"], "completion_condition_refs"),
        _strings(item["checkpoint_step_ids"], "checkpoint_step_ids"),
        _enum(PlanFailurePolicy, item["failure_policy"], "failure_policy"),
        tuple(
            _requirement(value)
            for value in _array(item["unmet_capabilities"], "unmet_capabilities")
        ),
        created_at,
        _strings(item["impossibility_blocker_ids"], "impossibility_blocker_ids"),
    )
    validate_plan_bounds(candidate, bounds_policy)
    return candidate


def _step(value: object) -> ActivityPlanStep:
    item = _mapping(value, "step")
    required = {
        "step_id",
        "activity_type",
        "operation_ref",
        "target_ref",
        "resume_activity_id",
        "dependency_step_ids",
        "required_capabilities",
        "precondition_ids",
        "completion_condition_refs",
        "interruption_policy",
        "retry_limit",
        "replan_on_failure",
    }
    if set(item) != required:
        raise ValueError("step fields do not match schema")
    target = item["target_ref"]
    if target is not None:
        target = _string(target, "target_ref")
    resume_activity = item["resume_activity_id"]
    if resume_activity is not None:
        resume_activity = _string(resume_activity, "resume_activity_id")
    requirements = tuple(
        _requirement(value)
        for value in _array(item["required_capabilities"], "required_capabilities")
    )
    replan = item["replan_on_failure"]
    if type(replan) is not bool:
        raise ValueError("replan_on_failure must be bool")
    return ActivityPlanStep(
        _string(item["step_id"], "step_id"),
        _string(item["activity_type"], "activity_type"),
        _string(item["operation_ref"], "operation_ref"),
        target,
        resume_activity,
        _strings(item["dependency_step_ids"], "dependency_step_ids"),
        requirements,
        _strings(item["precondition_ids"], "precondition_ids"),
        _strings(item["completion_condition_refs"], "completion_condition_refs"),
        _enum(InterruptionPolicy, item["interruption_policy"], "interruption_policy"),
        _revision(item["retry_limit"], "retry_limit"),
        replan,
    )


def _requirement(value: object) -> CapabilityRequirement:
    item = _mapping(value, "capability requirement")
    if set(item) != {"capability_type", "operation", "allow_degraded"}:
        raise ValueError("capability requirement fields do not match schema")
    degraded = item["allow_degraded"]
    if type(degraded) is not bool:
        raise ValueError("allow_degraded must be bool")
    return CapabilityRequirement(
        _string(item["capability_type"], "capability_type"),
        _string(item["operation"], "operation"),
        degraded,
    )


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{name} must be an object")
    return cast(Mapping[str, object], value)


def _array(value: object, name: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{name} must be an array")
    return tuple(value)


def _strings(value: object, name: str) -> tuple[str, ...]:
    values = _array(value, name)
    if any(not isinstance(item, str) for item in values):
        raise ValueError(f"{name} must contain strings")
    return cast(tuple[str, ...], values)


def _string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value


def _revision(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative int")
    return value


def _enum(enum_type: type[E], value: object, name: str) -> E:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string enum")
    try:
        return enum_type(value)
    except ValueError as error:
        raise ValueError(f"{name} has an invalid value") from error
