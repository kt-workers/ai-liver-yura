from __future__ import annotations

from dataclasses import InitVar, dataclass
from datetime import datetime
from enum import Enum
from math import isclose, isfinite, sqrt
from typing import TypeVar, cast

from app.domain.body import AnatomicalRegion, AnatomicalSide, BodyState, CanonicalBodyModel, Vector3
from app.domain.body_expression import BodyExpressionAxis, BodyExpressionContext
from app.domain.contracts import (
    CapabilityDescriptor,
    CapabilityRequirement,
    PreconditionRef,
    RevisionVector,
)
from app.domain.contracts.common import require_aware, require_identifier, require_revision
from app.domain.executive import ExecutiveInterruptibility, ExecutivePriority


class BodyMotionConstraintKind(str, Enum):
    REGION_AVAILABILITY = "region_availability"
    CONTACT_REQUIREMENT = "contact_requirement"
    SPATIAL_BOUNDARY = "spatial_boundary"
    TARGET_AVOIDANCE = "target_avoidance"
    TIMING = "timing"
    BALANCE = "balance"
    PRESERVE_ACTIVE_MOTION = "preserve_active_motion"
    ENVIRONMENT = "environment"


class BodyMotionEffect(str, Enum):
    ORIENT = "orient"
    TRANSLATE = "translate"
    CONTACT = "contact"
    IMPULSE = "impulse"


class BodySpatialTargetKind(str, Enum):
    DIRECTION = "direction"
    TARGET_REF = "target_ref"


class BodyBalanceMode(str, Enum):
    STABLE_SUPPORT_REQUIRED = "stable_support_required"
    TEMPORARY_FLIGHT_ALLOWED = "temporary_flight_allowed"
    RECOVER_STABLE_SUPPORT = "recover_stable_support"


class BodyCoordinationMode(str, Enum):
    SYNCHRONIZED = "synchronized"
    COUPLED = "coupled"
    COUNTERBALANCED = "counterbalanced"
    STAGGERED = "staggered"


class BodyMotionPlanningFailureCode(str, Enum):
    STALE = "stale"
    REPLAN_REQUIRED = "replan_required"
    INVALID = "invalid"
    SUPERSEDED = "superseded"


class BodyMotionPlanningError(ValueError):
    def __init__(self, code: BodyMotionPlanningFailureCode) -> None:
        super().__init__(code.value)
        self.code = code


T = TypeVar("T")
_PLAN_PROOF = object()


def _owned(
    values: object, item_type: type[T], name: str, *, non_empty: bool = False
) -> tuple[T, ...]:
    if not isinstance(values, (tuple, list)):
        raise ValueError(f"{name} は配列でなければなりません")
    result = tuple(values)
    if any(not isinstance(item, item_type) for item in result):
        raise ValueError(f"{name} が不正です")
    if non_empty and not result:
        raise ValueError(f"{name} は空にできません")
    return cast(tuple[T, ...], result)


def _ids(values: object, name: str, *, non_empty: bool = False) -> tuple[str, ...]:
    result = _owned(values, str, name, non_empty=non_empty)
    if any(not item.strip() for item in result) or len(result) != len(set(result)):
        raise ValueError(f"{name} は一意な非空identifierでなければなりません")
    return result


def _unit(value: float, name: str, *, positive: bool = False) -> float:
    if type(value) not in (int, float) or not isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"{name} は有限の [0, 1] でなければなりません")
    result = float(value)
    if positive and result <= 0:
        raise ValueError(f"{name} は0より大きくなければなりません")
    return result


@dataclass(frozen=True, slots=True)
class BodyMotionConstraintView:
    constraint_id: str
    kind: BodyMotionConstraintKind
    source_owner: str
    source_ref: str
    source_revision: int
    semantic_description: str
    subject_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("constraint_id", "source_owner", "source_ref", "semantic_description"):
            require_identifier(getattr(self, name), name)
        if not isinstance(self.kind, BodyMotionConstraintKind):
            raise ValueError("kind が不正です")
        require_revision(self.source_revision, "source_revision")
        object.__setattr__(self, "subject_refs", _ids(self.subject_refs, "subject_refs"))


@dataclass(frozen=True, slots=True)
class BodyMotionIntentView:
    decision_id: str
    intent_id: str
    purpose: str
    motion_goal_ref: str
    target_ref: str | None
    constraint_refs: tuple[str, ...]
    source_event_ids: tuple[str, ...]
    revisions: RevisionVector
    priority: ExecutivePriority
    interruptibility: ExecutiveInterruptibility
    preconditions: tuple[PreconditionRef, ...]
    required_capabilities: tuple[CapabilityRequirement, ...]

    def __post_init__(self) -> None:
        for name in ("decision_id", "intent_id", "purpose", "motion_goal_ref"):
            require_identifier(getattr(self, name), name)
        if self.target_ref is not None:
            require_identifier(self.target_ref, "target_ref")
        object.__setattr__(self, "constraint_refs", _ids(self.constraint_refs, "constraint_refs"))
        object.__setattr__(
            self,
            "source_event_ids",
            _ids(self.source_event_ids, "source_event_ids", non_empty=True),
        )
        if not isinstance(self.revisions, RevisionVector):
            raise ValueError("revisions が不正です")
        if not isinstance(self.priority, ExecutivePriority) or not isinstance(
            self.interruptibility, ExecutiveInterruptibility
        ):
            raise ValueError("Executive metadata が不正です")
        preconditions = _owned(self.preconditions, PreconditionRef, "preconditions")
        capabilities = _owned(
            self.required_capabilities, CapabilityRequirement, "required_capabilities"
        )
        if len({item.precondition_id for item in preconditions}) != len(preconditions):
            raise ValueError("precondition は一意でなければなりません")
        if len(set(capabilities)) != len(capabilities):
            raise ValueError("capability は一意でなければなりません")
        object.__setattr__(self, "preconditions", preconditions)
        object.__setattr__(self, "required_capabilities", capabilities)


@dataclass(frozen=True, slots=True)
class BodyMotionSelector:
    region: AnatomicalRegion | None = None
    side: AnatomicalSide | None = None
    chain_ids: tuple[str, ...] = ()
    end_effector_joint_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.region is not None and not isinstance(self.region, AnatomicalRegion):
            raise ValueError("region が不正です")
        if self.side is not None and not isinstance(self.side, AnatomicalSide):
            raise ValueError("side が不正です")
        object.__setattr__(self, "chain_ids", _ids(self.chain_ids, "chain_ids"))
        object.__setattr__(
            self,
            "end_effector_joint_ids",
            _ids(self.end_effector_joint_ids, "end_effector_joint_ids"),
        )


@dataclass(frozen=True, slots=True)
class BodySpatialTarget:
    kind: BodySpatialTargetKind
    direction: Vector3 | None
    target_ref: str | None
    extent: float

    def __post_init__(self) -> None:
        if not isinstance(self.kind, BodySpatialTargetKind):
            raise ValueError("kind が不正です")
        object.__setattr__(self, "extent", _unit(self.extent, "extent"))
        if self.kind is BodySpatialTargetKind.DIRECTION:
            if not isinstance(self.direction, Vector3) or self.target_ref is not None:
                raise ValueError("DIRECTION はdirectionだけを必要とします")
            magnitude = sqrt(self.direction.x**2 + self.direction.y**2 + self.direction.z**2)
            if not isclose(magnitude, 1.0, rel_tol=0.0, abs_tol=1e-6):
                raise ValueError("direction はnon-zero unit Vector3でなければなりません")
        else:
            if self.direction is not None or self.target_ref is None:
                raise ValueError("TARGET_REF はtarget_refだけを必要とします")
            require_identifier(self.target_ref, "target_ref")


@dataclass(frozen=True, slots=True)
class BodyMotionGoal:
    goal_id: str
    effect: BodyMotionEffect
    selector: BodyMotionSelector
    spatial_target: BodySpatialTarget | None
    intensity: float
    constraint_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.goal_id, "goal_id")
        if not isinstance(self.effect, BodyMotionEffect) or not isinstance(
            self.selector, BodyMotionSelector
        ):
            raise ValueError("goal が不正です")
        object.__setattr__(self, "intensity", _unit(self.intensity, "intensity"))
        object.__setattr__(self, "constraint_refs", _ids(self.constraint_refs, "constraint_refs"))
        has_region_or_chain = self.selector.region is not None or bool(self.selector.chain_ids)
        has_any_selector = has_region_or_chain or bool(self.selector.end_effector_joint_ids)
        if self.effect is BodyMotionEffect.ORIENT and (
            not has_region_or_chain or self.spatial_target is None
        ):
            raise ValueError("ORIENT はregion又はchainとspatial targetを必要とします")
        if self.effect is BodyMotionEffect.TRANSLATE and (
            not has_any_selector or self.spatial_target is None
        ):
            raise ValueError("TRANSLATE はselectorとspatial targetを必要とします")
        if self.effect is BodyMotionEffect.CONTACT and (
            not self.selector.end_effector_joint_ids
            or self.spatial_target is None
            or self.spatial_target.kind is not BodySpatialTargetKind.TARGET_REF
        ):
            raise ValueError("CONTACT はend-effectorとTARGET_REFを必要とします")
        if self.effect is BodyMotionEffect.IMPULSE and (
            not has_region_or_chain
            or self.spatial_target is None
            or self.spatial_target.kind is not BodySpatialTargetKind.DIRECTION
            or self.intensity <= 0
        ):
            raise ValueError("IMPULSE はroot/region/chain、DIRECTION、正のintensityを必要とします")


@dataclass(frozen=True, slots=True)
class BodyExpressionBinding:
    binding_id: str
    axis: BodyExpressionAxis
    influence: float

    def __post_init__(self) -> None:
        require_identifier(self.binding_id, "binding_id")
        if not isinstance(self.axis, BodyExpressionAxis):
            raise ValueError("axis が不正です")
        object.__setattr__(self, "influence", _unit(self.influence, "influence"))


@dataclass(frozen=True, slots=True)
class BodyMotionPhase:
    phase_id: str
    goal_ids: tuple[str, ...]
    relative_duration_weight: float
    balance_mode: BodyBalanceMode
    expression_binding_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.phase_id, "phase_id")
        object.__setattr__(self, "goal_ids", _ids(self.goal_ids, "goal_ids", non_empty=True))
        if (
            type(self.relative_duration_weight) not in (int, float)
            or not isfinite(self.relative_duration_weight)
            or self.relative_duration_weight <= 0
        ):
            raise ValueError("relative_duration_weight は正の有限値でなければなりません")
        object.__setattr__(self, "relative_duration_weight", float(self.relative_duration_weight))
        if not isinstance(self.balance_mode, BodyBalanceMode):
            raise ValueError("balance_mode が不正です")
        object.__setattr__(
            self,
            "expression_binding_ids",
            _ids(self.expression_binding_ids, "expression_binding_ids"),
        )


@dataclass(frozen=True, slots=True)
class BodyCoordinationConstraint:
    coordination_id: str
    goal_ids: tuple[str, ...]
    mode: BodyCoordinationMode

    def __post_init__(self) -> None:
        require_identifier(self.coordination_id, "coordination_id")
        object.__setattr__(self, "goal_ids", _ids(self.goal_ids, "goal_ids", non_empty=True))
        if len(self.goal_ids) < 2 or not isinstance(self.mode, BodyCoordinationMode):
            raise ValueError("coordination が不正です")


@dataclass(frozen=True, slots=True)
class DeterministicBodyPlanningDirective:
    goals: tuple[BodyMotionGoal, ...]
    phases: tuple[BodyMotionPhase, ...]
    coordination_constraints: tuple[BodyCoordinationConstraint, ...]
    expression_bindings: tuple[BodyExpressionBinding, ...]

    def __post_init__(self) -> None:
        goals = _owned(self.goals, BodyMotionGoal, "goals")
        phases = _owned(self.phases, BodyMotionPhase, "phases")
        coordination = _owned(
            self.coordination_constraints,
            BodyCoordinationConstraint,
            "coordination_constraints",
        )
        bindings = _owned(self.expression_bindings, BodyExpressionBinding, "expression_bindings")
        _validate_shape(goals, phases, coordination, bindings)
        object.__setattr__(self, "goals", goals)
        object.__setattr__(self, "phases", phases)
        object.__setattr__(self, "coordination_constraints", coordination)
        object.__setattr__(self, "expression_bindings", bindings)


@dataclass(frozen=True, slots=True)
class BodyMotionPlanningContextSnapshot:
    request_id: str
    intent: BodyMotionIntentView
    body_model: CanonicalBodyModel
    body_state: BodyState
    expression: BodyExpressionContext
    constraints: tuple[BodyMotionConstraintView, ...]
    capabilities: tuple[CapabilityDescriptor, ...]
    captured_at: datetime
    trace_id: str
    deterministic_directive: DeterministicBodyPlanningDirective | None = None

    def __post_init__(self) -> None:
        for name in ("request_id", "trace_id"):
            require_identifier(getattr(self, name), name)
        if not isinstance(self.intent, BodyMotionIntentView) or not isinstance(
            self.body_model, CanonicalBodyModel
        ):
            raise ValueError("planning source が不正です")
        if not isinstance(self.body_state, BodyState) or not isinstance(
            self.expression, BodyExpressionContext
        ):
            raise ValueError("planning snapshot が不正です")
        self.body_state.validate_for(self.body_model)
        constraints = _owned(self.constraints, BodyMotionConstraintView, "constraints")
        if {item.constraint_id for item in constraints} != set(self.intent.constraint_refs):
            raise ValueError("constraint はintent refsと完全一致しなければなりません")
        if len({item.constraint_id for item in constraints}) != len(constraints):
            raise ValueError("constraint_id は一意でなければなりません")
        if len({(item.source_owner, item.source_ref) for item in constraints}) != len(constraints):
            raise ValueError("constraint source identity は一意でなければなりません")
        object.__setattr__(self, "constraints", constraints)
        capabilities = _owned(self.capabilities, CapabilityDescriptor, "capabilities")
        if len({item.capability_id for item in capabilities}) != len(capabilities):
            raise ValueError("capability_id は一意でなければなりません")
        if not all(
            any(item.satisfies(requirement) for item in capabilities)
            for requirement in self.intent.required_capabilities
        ):
            raise ValueError("required capability を満たすsnapshotが必要です")
        object.__setattr__(self, "capabilities", capabilities)
        if self.deterministic_directive is not None and not isinstance(
            self.deterministic_directive,
            DeterministicBodyPlanningDirective,
        ):
            raise ValueError("deterministic_directive が不正です")
        require_aware(self.captured_at, "captured_at")


@dataclass(frozen=True, slots=True)
class BodyMotionPlanCandidate:
    candidate_id: str
    request_id: str
    source_decision_id: str
    source_intent_id: str
    revisions: RevisionVector
    body_model_id: str
    planning_body_state_revision: int
    planning_expression_revision: int
    planning_constraints: tuple[BodyMotionConstraintView, ...]
    goals: tuple[BodyMotionGoal, ...]
    phases: tuple[BodyMotionPhase, ...]
    coordination_constraints: tuple[BodyCoordinationConstraint, ...]
    expression_bindings: tuple[BodyExpressionBinding, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "candidate_id",
            "request_id",
            "source_decision_id",
            "source_intent_id",
            "body_model_id",
        ):
            require_identifier(getattr(self, name), name)
        if not isinstance(self.revisions, RevisionVector):
            raise ValueError("revisions が不正です")
        for name in ("planning_body_state_revision", "planning_expression_revision"):
            require_revision(getattr(self, name), name)
        for field, typ in (
            ("planning_constraints", BodyMotionConstraintView),
            ("goals", BodyMotionGoal),
            ("phases", BodyMotionPhase),
            ("coordination_constraints", BodyCoordinationConstraint),
            ("expression_bindings", BodyExpressionBinding),
        ):
            object.__setattr__(self, field, _owned(getattr(self, field), typ, field))
        _validate_shape(
            self.goals, self.phases, self.coordination_constraints, self.expression_bindings
        )
        require_aware(self.created_at, "created_at")


def _validate_shape(
    goals: tuple[BodyMotionGoal, ...],
    phases: tuple[BodyMotionPhase, ...],
    coordination: tuple[BodyCoordinationConstraint, ...],
    bindings: tuple[BodyExpressionBinding, ...],
) -> None:
    if not goals or not phases:
        raise ValueError("goals と phases は空にできません")
    for values, attribute, name in (
        (goals, "goal_id", "goal_id"),
        (phases, "phase_id", "phase_id"),
        (coordination, "coordination_id", "coordination_id"),
        (bindings, "binding_id", "binding_id"),
    ):
        identifiers = [getattr(item, attribute) for item in values]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError(f"{name} は一意でなければなりません")
    goal_ids = {item.goal_id for item in goals}
    binding_ids = {item.binding_id for item in bindings}
    if {item for phase in phases for item in phase.goal_ids} != goal_ids:
        raise ValueError("phase goal refs は全goalを一度以上参照しなければなりません")
    if any(set(phase.expression_binding_ids) - binding_ids for phase in phases):
        raise ValueError("phase expression binding ref が不正です")
    if any(set(item.goal_ids) - goal_ids for item in coordination):
        raise ValueError("coordination goal ref が不正です")


@dataclass(frozen=True, slots=True)
class BodyMotionPlan:
    plan_id: str
    candidate: BodyMotionPlanCandidate
    motion_goal_ref: str
    priority: ExecutivePriority
    interruptibility: ExecutiveInterruptibility
    preconditions: tuple[PreconditionRef, ...]
    required_capabilities: tuple[CapabilityRequirement, ...]
    committed_at: datetime
    _proof: InitVar[object | None] = None

    def __post_init__(self, _proof: object | None) -> None:
        if _proof is not _PLAN_PROOF:
            raise ValueError("BodyMotionPlan はAuthorityだけが生成できます")
        require_identifier(self.plan_id, "plan_id")
        if not isinstance(self.candidate, BodyMotionPlanCandidate):
            raise ValueError("candidate が不正です")
        require_identifier(self.motion_goal_ref, "motion_goal_ref")
        if not isinstance(self.priority, ExecutivePriority) or not isinstance(
            self.interruptibility, ExecutiveInterruptibility
        ):
            raise ValueError("trusted metadata が不正です")
        object.__setattr__(
            self, "preconditions", _owned(self.preconditions, PreconditionRef, "preconditions")
        )
        object.__setattr__(
            self,
            "required_capabilities",
            _owned(self.required_capabilities, CapabilityRequirement, "required_capabilities"),
        )
        require_aware(self.committed_at, "committed_at")


@dataclass(frozen=True, slots=True)
class BodyMotionPlanningCommitState:
    revisions: RevisionVector
    active_intent: BodyMotionIntentView | None
    body_model: CanonicalBodyModel
    body_state: BodyState
    expression: BodyExpressionContext
    constraints: tuple[BodyMotionConstraintView, ...]
    capabilities: tuple[CapabilityDescriptor, ...]
    preconditions: tuple[PreconditionRef, ...]
    captured_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.revisions, RevisionVector) or not isinstance(
            self.body_model, CanonicalBodyModel
        ):
            raise ValueError("commit state が不正です")
        if not isinstance(self.body_state, BodyState) or not isinstance(
            self.expression, BodyExpressionContext
        ):
            raise ValueError("commit state snapshot が不正です")
        self.body_state.validate_for(self.body_model)
        object.__setattr__(
            self, "constraints", _owned(self.constraints, BodyMotionConstraintView, "constraints")
        )
        object.__setattr__(
            self, "capabilities", _owned(self.capabilities, CapabilityDescriptor, "capabilities")
        )
        object.__setattr__(
            self, "preconditions", _owned(self.preconditions, PreconditionRef, "preconditions")
        )
        require_aware(self.captured_at, "captured_at")
