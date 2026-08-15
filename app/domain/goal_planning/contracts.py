from __future__ import annotations

from dataclasses import InitVar, dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol, TypeVar, cast

from app.domain.contracts import (
    CapabilityDescriptor,
    CapabilityRequirement,
    ExecutionStatus,
    RevisionVector,
)
from app.domain.contracts.common import (
    require_aware,
    require_identifier,
    require_revision,
    timestamp_to_json,
    utc_instant,
)
from app.domain.goals import GoalContextView, GoalState, GoalStatus, InterruptionPolicy


class GoalPlanningOutcome(str, Enum):
    PLANNED = "planned"
    NO_PLAN_REQUIRED = "no_plan_required"
    IMPOSSIBLE = "impossible"


class PlanFailurePolicy(str, Enum):
    FAIL = "fail"
    RETRY_BOUNDED = "retry_bounded"
    REPLAN_REQUIRED = "replan_required"


class PlanningBlockerKind(str, Enum):
    PRECONDITION_UNSATISFIED = "precondition_unsatisfied"
    CONSTRAINT_CONFLICT = "constraint_conflict"


T = TypeVar("T")
_PLAN_PROOF = object()


class _PlanShape(Protocol):
    @property
    def outcome(self) -> GoalPlanningOutcome: ...

    @property
    def steps(self) -> tuple[ActivityPlanStep, ...]: ...

    @property
    def completion_condition_refs(self) -> tuple[str, ...]: ...

    @property
    def checkpoint_step_ids(self) -> tuple[str, ...]: ...

    @property
    def failure_policy(self) -> PlanFailurePolicy: ...

    @property
    def unmet_capabilities(self) -> tuple[CapabilityRequirement, ...]: ...

    @property
    def impossibility_blocker_ids(self) -> tuple[str, ...]: ...


def _owned(values: object, expected: type[T], name: str) -> tuple[T, ...]:
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{name} must be an array")
    result = tuple(values)
    if any(not isinstance(item, expected) for item in result):
        raise ValueError(f"{name} contains an invalid value")
    return cast(tuple[T, ...], result)


def _ids(values: object, name: str, *, non_empty: bool = False) -> tuple[str, ...]:
    result = _owned(values, str, name)
    if any(not item.strip() for item in result):
        raise ValueError(f"{name} must contain non-empty strings")
    if len(result) != len(set(result)):
        raise ValueError(f"{name} must be unique")
    if non_empty and not result:
        raise ValueError(f"{name} must not be empty")
    return result


@dataclass(frozen=True, slots=True)
class PlanningBlocker:
    blocker_id: str
    kind: PlanningBlockerKind
    subject_ref: str

    def __post_init__(self) -> None:
        require_identifier(self.blocker_id, "blocker_id")
        if not isinstance(self.kind, PlanningBlockerKind):
            raise ValueError("kind must be PlanningBlockerKind")
        require_identifier(self.subject_ref, "subject_ref")

    def to_dict(self) -> dict[str, object]:
        return {
            "blocker_id": self.blocker_id,
            "kind": self.kind.value,
            "subject_ref": self.subject_ref,
        }


@dataclass(frozen=True, slots=True)
class ActivityContextRef:
    activity_id: str
    goal_id: str
    operation_ref: str
    status: ExecutionStatus
    effect_refs: tuple[str, ...] = ()
    activity_type: str | None = None
    capability_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("activity_id", "goal_id", "operation_ref"):
            require_identifier(getattr(self, name), name)
        for name in ("activity_type", "capability_id"):
            value = getattr(self, name)
            if value is not None:
                require_identifier(value, name)
        if not isinstance(self.status, ExecutionStatus):
            raise ValueError("status must be ExecutionStatus")
        object.__setattr__(self, "effect_refs", _ids(self.effect_refs, "effect_refs"))

    def to_dict(self) -> dict[str, object]:
        return {
            "activity_id": self.activity_id,
            "goal_id": self.goal_id,
            "activity_type": self.activity_type,
            "capability_id": self.capability_id,
            "operation_ref": self.operation_ref,
            "status": self.status.value,
            "effect_refs": list(self.effect_refs),
        }


@dataclass(frozen=True, slots=True)
class ActivityPlanStep:
    step_id: str
    activity_type: str
    operation_ref: str
    target_ref: str | None
    resume_activity_id: str | None
    dependency_step_ids: tuple[str, ...]
    required_capabilities: tuple[CapabilityRequirement, ...]
    precondition_ids: tuple[str, ...]
    completion_condition_refs: tuple[str, ...]
    interruption_policy: InterruptionPolicy
    retry_limit: int
    replan_on_failure: bool

    def __post_init__(self) -> None:
        for name in ("step_id", "activity_type", "operation_ref"):
            require_identifier(getattr(self, name), name)
        if self.target_ref is not None:
            require_identifier(self.target_ref, "target_ref")
        if self.resume_activity_id is not None:
            require_identifier(self.resume_activity_id, "resume_activity_id")
        for name in (
            "dependency_step_ids",
            "precondition_ids",
            "completion_condition_refs",
        ):
            object.__setattr__(self, name, _ids(getattr(self, name), name))
        requirements = _owned(
            self.required_capabilities,
            CapabilityRequirement,
            "required_capabilities",
        )
        if not requirements:
            raise ValueError("required_capabilities must not be empty")
        if len(requirements) != len(set(requirements)):
            raise ValueError("required_capabilities must be unique")
        object.__setattr__(self, "required_capabilities", requirements)
        if not isinstance(self.interruption_policy, InterruptionPolicy):
            raise ValueError("interruption_policy must be InterruptionPolicy")
        if type(self.retry_limit) is not int or self.retry_limit < 0:
            raise ValueError("retry_limit must be a non-negative int")
        if type(self.replan_on_failure) is not bool:
            raise ValueError("replan_on_failure must be bool")

    def to_dict(self) -> dict[str, object]:
        return {
            "step_id": self.step_id,
            "activity_type": self.activity_type,
            "operation_ref": self.operation_ref,
            "target_ref": self.target_ref,
            "resume_activity_id": self.resume_activity_id,
            "dependency_step_ids": list(self.dependency_step_ids),
            "required_capabilities": [item.to_dict() for item in self.required_capabilities],
            "precondition_ids": list(self.precondition_ids),
            "completion_condition_refs": list(self.completion_condition_refs),
            "interruption_policy": self.interruption_policy.value,
            "retry_limit": self.retry_limit,
            "replan_on_failure": self.replan_on_failure,
        }


@dataclass(frozen=True, slots=True)
class DeterministicPlanningDirective:
    outcome: GoalPlanningOutcome
    steps: tuple[ActivityPlanStep, ...]
    completion_condition_refs: tuple[str, ...]
    checkpoint_step_ids: tuple[str, ...]
    failure_policy: PlanFailurePolicy
    unmet_capabilities: tuple[CapabilityRequirement, ...] = ()
    impossibility_blocker_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_plan_shape(self)

    def to_dict(self) -> dict[str, object]:
        return _plan_shape_dict(self)


@dataclass(frozen=True, slots=True)
class GoalPlanningContextSnapshot:
    revisions: RevisionVector
    goal_context: GoalContextView
    goal: GoalState
    source_event_ids: tuple[str, ...]
    capabilities: tuple[CapabilityDescriptor, ...]
    planning_requirements: tuple[CapabilityRequirement, ...]
    activities: tuple[ActivityContextRef, ...]
    captured_at: datetime
    deterministic_directive: DeterministicPlanningDirective | None = None
    planning_blockers: tuple[PlanningBlocker, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.revisions, RevisionVector):
            raise ValueError("revisions must be RevisionVector")
        if self.revisions.goal_revision is None:
            raise ValueError("goal_revision is required for planning")
        if not isinstance(self.goal_context, GoalContextView):
            raise ValueError("goal_context must be GoalContextView")
        if not isinstance(self.goal, GoalState):
            raise ValueError("goal must be GoalState")
        if self.goal.status is not GoalStatus.ACTIVE:
            raise ValueError("planning requires an active goal")
        if self.goal_context.goal_revision != self.revisions.goal_revision:
            raise ValueError("goal context revision must match revisions")
        matches = [
            item for item in self.goal_context.active_goals if item.goal_id == self.goal.goal_id
        ]
        if matches != [self.goal]:
            raise ValueError("goal must exactly match one active goal in context")
        object.__setattr__(
            self,
            "source_event_ids",
            _ids(self.source_event_ids, "source_event_ids", non_empty=True),
        )
        capabilities = _owned(self.capabilities, CapabilityDescriptor, "capabilities")
        planning_requirements = _owned(
            self.planning_requirements,
            CapabilityRequirement,
            "planning_requirements",
        )
        if len(planning_requirements) != len(set(planning_requirements)):
            raise ValueError("planning_requirements must be unique")
        blockers = _owned(self.planning_blockers, PlanningBlocker, "planning_blockers")
        if len({item.blocker_id for item in blockers}) != len(blockers):
            raise ValueError("planning blocker ids must be unique")
        if any(
            item.kind is PlanningBlockerKind.PRECONDITION_UNSATISFIED
            and item.subject_ref not in self.goal.precondition_ids
            for item in blockers
        ):
            raise ValueError("precondition blocker is outside target goal")
        activities = _owned(self.activities, ActivityContextRef, "activities")
        for values, attribute, name in (
            (capabilities, "capability_id", "capability ids"),
            (activities, "activity_id", "activity ids"),
        ):
            identifiers = [getattr(item, attribute) for item in values]
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"{name} must be unique")
        if any(item.goal_id != self.goal.goal_id for item in activities):
            raise ValueError("activity context must belong to target goal")
        normalized_activities: list[ActivityContextRef] = []
        for activity in activities:
            matches = [
                descriptor
                for descriptor in capabilities
                if activity.operation_ref in descriptor.operations
                and (
                    activity.activity_type is None
                    or descriptor.capability_type == activity.activity_type
                )
                and (
                    activity.capability_id is None
                    or descriptor.capability_id == activity.capability_id
                )
            ]
            if len(matches) != 1:
                raise ValueError(
                    "activity context capability identity must resolve "
                    "exactly one bounded capability"
                )
            descriptor = matches[0]
            normalized_activities.append(
                ActivityContextRef(
                    activity.activity_id,
                    activity.goal_id,
                    activity.operation_ref,
                    activity.status,
                    activity.effect_refs,
                    descriptor.capability_type,
                    descriptor.capability_id,
                )
            )
        activities = tuple(normalized_activities)
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "planning_requirements", planning_requirements)
        object.__setattr__(self, "activities", activities)
        object.__setattr__(self, "planning_blockers", blockers)
        require_aware(self.captured_at, "captured_at")
        if utc_instant(self.captured_at) < utc_instant(self.goal.updated_at):
            raise ValueError("snapshot cannot predate target goal")
        if self.deterministic_directive is not None:
            if not isinstance(self.deterministic_directive, DeterministicPlanningDirective):
                raise ValueError("deterministic_directive has an invalid type")
            _validate_refs(self.deterministic_directive, self)

    def to_dict(self) -> dict[str, object]:
        return {
            "revisions": self.revisions.to_dict(),
            "goal_context": self.goal_context.to_dict(),
            "goal": self.goal.to_dict(),
            "source_event_ids": list(self.source_event_ids),
            "capabilities": [item.to_dict() for item in self.capabilities],
            "planning_requirements": [item.to_dict() for item in self.planning_requirements],
            "planning_blockers": [item.to_dict() for item in self.planning_blockers],
            "activities": [item.to_dict() for item in self.activities],
            "captured_at": timestamp_to_json(self.captured_at),
            "deterministic_directive": None
            if self.deterministic_directive is None
            else self.deterministic_directive.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class GoalPlanningCandidate:
    candidate_id: str
    goal_id: str
    goal_state_revision: int
    source_event_ids: tuple[str, ...]
    revisions: RevisionVector
    outcome: GoalPlanningOutcome
    steps: tuple[ActivityPlanStep, ...]
    completion_condition_refs: tuple[str, ...]
    checkpoint_step_ids: tuple[str, ...]
    failure_policy: PlanFailurePolicy
    unmet_capabilities: tuple[CapabilityRequirement, ...]
    created_at: datetime
    impossibility_blocker_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("candidate_id", "goal_id"):
            require_identifier(getattr(self, name), name)
        require_revision(self.goal_state_revision, "goal_state_revision")
        object.__setattr__(
            self,
            "source_event_ids",
            _ids(self.source_event_ids, "source_event_ids", non_empty=True),
        )
        if not isinstance(self.revisions, RevisionVector):
            raise ValueError("revisions must be RevisionVector")
        _validate_plan_shape(self)
        require_aware(self.created_at, "created_at")

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "goal_id": self.goal_id,
            "goal_state_revision": self.goal_state_revision,
            "source_event_ids": list(self.source_event_ids),
            "revisions": self.revisions.to_dict(),
            **_plan_shape_dict(self),
            "created_at": timestamp_to_json(self.created_at),
        }


@dataclass(frozen=True, slots=True)
class GoalPlanningCommitState:
    revisions: RevisionVector
    goal: GoalState
    capabilities: tuple[CapabilityDescriptor, ...]
    planning_blockers: tuple[PlanningBlocker, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.revisions, RevisionVector):
            raise ValueError("revisions must be RevisionVector")
        if not isinstance(self.goal, GoalState):
            raise ValueError("goal must be GoalState")
        capabilities = _owned(self.capabilities, CapabilityDescriptor, "capabilities")
        if len({item.capability_id for item in capabilities}) != len(capabilities):
            raise ValueError("capability ids must be unique")
        blockers = _owned(self.planning_blockers, PlanningBlocker, "planning_blockers")
        if len({item.blocker_id for item in blockers}) != len(blockers):
            raise ValueError("planning blocker ids must be unique")
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "planning_blockers", blockers)


@dataclass(frozen=True, slots=True)
class ActivityPlan:
    plan_id: str
    candidate: GoalPlanningCandidate
    committed_at: datetime
    _proof: InitVar[object | None] = None

    def __post_init__(self, _proof: object | None) -> None:
        if _proof is not _PLAN_PROOF:
            raise ValueError("ActivityPlan must be created by GoalPlanningAuthority")
        require_identifier(self.plan_id, "plan_id")
        if not isinstance(self.candidate, GoalPlanningCandidate):
            raise ValueError("candidate must be GoalPlanningCandidate")
        require_aware(self.committed_at, "committed_at")
        if utc_instant(self.committed_at) < utc_instant(self.candidate.created_at):
            raise ValueError("plan cannot predate candidate")

    def to_dict(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "candidate": self.candidate.to_dict(),
            "committed_at": timestamp_to_json(self.committed_at),
        }


def _validate_plan_shape(value: _PlanShape) -> None:
    outcome = value.outcome
    failure_policy = value.failure_policy
    if not isinstance(outcome, GoalPlanningOutcome):
        raise ValueError("outcome must be GoalPlanningOutcome")
    if not isinstance(failure_policy, PlanFailurePolicy):
        raise ValueError("failure_policy must be PlanFailurePolicy")
    steps = _owned(value.steps, ActivityPlanStep, "steps")
    completion_refs = _ids(value.completion_condition_refs, "completion_condition_refs")
    checkpoint_ids = _ids(value.checkpoint_step_ids, "checkpoint_step_ids")
    unmet = _owned(
        value.unmet_capabilities,
        CapabilityRequirement,
        "unmet_capabilities",
    )
    blocker_ids = _ids(value.impossibility_blocker_ids, "impossibility_blocker_ids")
    if len(unmet) != len(set(unmet)):
        raise ValueError("unmet_capabilities must be unique")
    object.__setattr__(value, "steps", steps)
    object.__setattr__(value, "completion_condition_refs", completion_refs)
    object.__setattr__(value, "checkpoint_step_ids", checkpoint_ids)
    object.__setattr__(value, "unmet_capabilities", unmet)
    object.__setattr__(value, "impossibility_blocker_ids", blocker_ids)
    ids = [item.step_id for item in steps]
    if len(ids) != len(set(ids)):
        raise ValueError("step ids must be unique")
    known = set(ids)
    if any(item.step_id in item.dependency_step_ids for item in steps):
        raise ValueError("step cannot depend on itself")
    if any(ref not in known for item in steps for ref in item.dependency_step_ids):
        raise ValueError("step dependency is outside candidate")
    if any(ref not in known for ref in checkpoint_ids):
        raise ValueError("checkpoint is outside candidate")
    _reject_cycles(steps)
    if outcome is GoalPlanningOutcome.PLANNED:
        if not steps or not completion_refs or unmet or blocker_ids:
            raise ValueError(
                "planned outcome requires plan structure without impossibility reasons"
            )
    elif steps or completion_refs or checkpoint_ids:
        raise ValueError("non-planned outcome cannot contain plan structure")
    elif outcome is GoalPlanningOutcome.IMPOSSIBLE and not (unmet or blocker_ids):
        raise ValueError("impossible outcome requires a trusted impossibility reason")
    elif outcome is GoalPlanningOutcome.NO_PLAN_REQUIRED and (unmet or blocker_ids):
        raise ValueError("no-plan outcome cannot contain impossibility reasons")
    if outcome is not GoalPlanningOutcome.PLANNED:
        if failure_policy is not PlanFailurePolicy.FAIL:
            raise ValueError("non-planned outcome requires fail policy")
    elif failure_policy is PlanFailurePolicy.FAIL and any(
        item.retry_limit or item.replan_on_failure for item in steps
    ):
        raise ValueError("fail policy cannot contain retry or replan behavior")
    elif failure_policy is PlanFailurePolicy.RETRY_BOUNDED and (
        not any(item.retry_limit > 0 for item in steps)
        or any(item.replan_on_failure for item in steps)
    ):
        raise ValueError("retry policy requires retry without replan behavior")
    elif failure_policy is PlanFailurePolicy.REPLAN_REQUIRED and not any(
        item.replan_on_failure for item in steps
    ):
        raise ValueError("replan policy requires a replan step")


def _reject_cycles(steps: tuple[ActivityPlanStep, ...]) -> None:
    dependencies = {item.step_id: item.dependency_step_ids for item in steps}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(step_id: str) -> None:
        if step_id in visiting:
            raise ValueError("step dependencies must be acyclic")
        if step_id in visited:
            return
        visiting.add(step_id)
        for dependency in dependencies[step_id]:
            visit(dependency)
        visiting.remove(step_id)
        visited.add(step_id)

    for step_id in dependencies:
        visit(step_id)


def _activity_matches_step(
    activity: ActivityContextRef,
    step: ActivityPlanStep,
    descriptors: dict[str, CapabilityDescriptor],
) -> bool:
    if (
        activity.activity_type is None
        or activity.capability_id is None
        or activity.activity_type != step.activity_type
        or activity.operation_ref != step.operation_ref
    ):
        return False
    descriptor = descriptors.get(activity.capability_id)
    return (
        descriptor is not None
        and descriptor.capability_type == step.activity_type
        and step.operation_ref in descriptor.operations
        and all(descriptor.satisfies(requirement) for requirement in step.required_capabilities)
    )


def _validate_refs(value: _PlanShape, snapshot: GoalPlanningContextSnapshot) -> None:
    goal = snapshot.goal
    steps = value.steps
    if any(item.target_ref not in {None, goal.target_ref} for item in steps):
        raise ValueError("step target is outside target goal")
    preconditions = set(goal.precondition_ids)
    completions = set(goal.completion_condition_refs)
    if any(ref not in preconditions for item in steps for ref in item.precondition_ids):
        raise ValueError("step precondition is outside target goal")
    if any(ref not in completions for item in steps for ref in item.completion_condition_refs):
        raise ValueError("step completion is outside target goal")
    if any(ref not in completions for ref in value.completion_condition_refs):
        raise ValueError("plan completion is outside target goal")
    descriptors = {item.capability_id: item for item in snapshot.capabilities}
    for step in steps:
        if not any(
            descriptor.capability_type == step.activity_type
            and step.operation_ref in descriptor.operations
            and all(descriptor.satisfies(requirement) for requirement in step.required_capabilities)
            for descriptor in snapshot.capabilities
        ):
            raise ValueError("step capability is unavailable in snapshot")
        active_matches = [
            activity
            for activity in snapshot.activities
            if _activity_matches_step(activity, step, descriptors)
            and activity.status
            not in {
                ExecutionStatus.COMPLETED,
                ExecutionStatus.REJECTED,
                ExecutionStatus.UNSUPPORTED,
                ExecutionStatus.FAILED,
                ExecutionStatus.CANCELLED,
                ExecutionStatus.TIMED_OUT,
                ExecutionStatus.SUPERSEDED,
            }
        ]
        if step.resume_activity_id is None and active_matches:
            raise ValueError("nonterminal activity requires explicit resume reference")
        if step.resume_activity_id is not None and not any(
            item.activity_id == step.resume_activity_id for item in active_matches
        ):
            raise ValueError("resume activity is outside matching nonterminal context")
    realized_requirements = {
        requirement for step in steps for requirement in step.required_capabilities
    }
    if value.outcome is GoalPlanningOutcome.PLANNED and not set(
        snapshot.planning_requirements
    ).issubset(realized_requirements):
        raise ValueError("plan omits trusted capability requirement")
    if value.outcome is GoalPlanningOutcome.IMPOSSIBLE and not set(
        value.unmet_capabilities
    ).issubset(snapshot.planning_requirements):
        raise ValueError("unmet capability is outside trusted requirements")
    for requirement in value.unmet_capabilities:
        if any(descriptor.satisfies(requirement) for descriptor in snapshot.capabilities):
            raise ValueError("unmet capability is available in snapshot")
    trusted_blockers = {item.blocker_id for item in snapshot.planning_blockers}
    if value.outcome is GoalPlanningOutcome.IMPOSSIBLE and not set(
        value.impossibility_blocker_ids
    ).issubset(trusted_blockers):
        raise ValueError("impossibility blocker is outside trusted planning blockers")


def _plan_shape_dict(value: _PlanShape) -> dict[str, object]:
    return {
        "outcome": value.outcome.value,
        "steps": [item.to_dict() for item in value.steps],
        "completion_condition_refs": list(value.completion_condition_refs),
        "checkpoint_step_ids": list(value.checkpoint_step_ids),
        "failure_policy": value.failure_policy.value,
        "unmet_capabilities": [item.to_dict() for item in value.unmet_capabilities],
        "impossibility_blocker_ids": list(value.impossibility_blocker_ids),
    }
