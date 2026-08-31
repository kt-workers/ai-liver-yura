from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from typing import cast

import pytest

from app.domain.body import (
    AnatomicalRegion,
    AnatomicalSide,
    Axis,
    BodyPose,
    BodyState,
    BodyVelocity,
    CanonicalBodyModel,
    CenterOfMassReference,
    JointDefinition,
    JointLimit,
    JointTransform,
    JointVelocity,
    KinematicChain,
    Quaternion,
    SegmentDefinition,
    Vector3,
)
from app.domain.body_expression import (
    BodyExpressionAxis,
    BodyExpressionAxisValue,
    BodyExpressionContext,
    BodyFocusExpressionConstraint,
    NormalizedExpressionValue,
)
from app.domain.body_motion_planning import (
    BodyBalanceMode,
    BodyCoordinationConstraint,
    BodyCoordinationMode,
    BodyExpressionBinding,
    BodyMotionConstraintKind,
    BodyMotionConstraintView,
    BodyMotionEffect,
    BodyMotionGoal,
    BodyMotionIntentView,
    BodyMotionPhase,
    BodyMotionPlanAuthority,
    BodyMotionPlanCandidate,
    BodyMotionPlanner,
    BodyMotionPlanningCommitState,
    BodyMotionPlanningContextSnapshot,
    BodyMotionPlanningPolicy,
    BodyMotionSelector,
    BodySpatialTarget,
    BodySpatialTargetKind,
    DeterministicBodyMotionPlanner,
    DeterministicBodyPlanningDirective,
    build_request,
    parse_candidate,
)
from app.domain.contracts import (
    AuthorityRef,
    CapabilityAvailability,
    CapabilityDescriptor,
    CapabilityRequirement,
    IntentKind,
    IntentRef,
    PreconditionRef,
    RevisionVector,
    SystemCommand,
)
from app.domain.contracts.common import JsonValue
from app.domain.contracts.execution import ExecutionResult
from app.domain.executive import (
    BodyIntentPayload,
    CommittedExecutiveDecision,
    ExecutiveBoundsProvenance,
    ExecutiveDecisionCandidate,
    ExecutiveIntent,
    ExecutiveIntentKind,
    ExecutiveInterruptibility,
    ExecutiveOutcome,
    ExecutivePriority,
)
from app.domain.llm import (
    LLMModelClass,
    LLMReasoningEffort,
    LLMRoleRequest,
    LLMRoleResult,
    LLMRoleStatus,
    LLMTokenUsage,
    StructuredPayload,
)
from tests.helpers.llm import make_execution_policy

NOW = datetime(2026, 8, 17, tzinfo=timezone.utc)
REVISIONS = RevisionVector(7, 5, 3)


def _transform() -> JointTransform:
    return JointTransform(Vector3(0, 0, 0), Quaternion(0, 0, 0, 1))


def _model() -> CanonicalBodyModel:
    root = JointDefinition(
        "root",
        None,
        AnatomicalRegion.ROOT,
        AnatomicalSide.CENTER,
        _transform(),
        (JointLimit(Axis.Z, -1, 1, -0.5, 0.5, 0),),
    )
    hand = JointDefinition(
        "right_hand",
        "root",
        AnatomicalRegion.HAND,
        AnatomicalSide.RIGHT,
        _transform(),
        (JointLimit(Axis.Z, -1, 1, -0.5, 0.5, 0),),
    )
    return CanonicalBodyModel(
        "body.v1",
        (root, hand),
        (SegmentDefinition("right_arm", "root", "right_hand", 0.4, 1.0),),
        ("right_hand",),
        (KinematicChain("right_arm", ("root", "right_hand"), "right_hand"),),
        CenterOfMassReference("root", Vector3(0, 0, 0)),
    )


def _state() -> BodyState:
    pose = BodyPose(_transform(), (("right_hand", _transform()),))
    velocity = BodyVelocity(
        JointVelocity(Vector3(0, 0, 0), Vector3(0, 0, 0)),
        (("right_hand", JointVelocity(Vector3(0, 0, 0), Vector3(0, 0, 0))),),
    )
    return BodyState("body.v1", 2, NOW, pose, velocity)


def _expression(revision: int = 4) -> BodyExpressionContext:
    return BodyExpressionContext(
        revision,
        7,
        2,
        7,
        3,
        7,
        "generic",
        1,
        1,
        "policy",
        1,
        tuple(
            BodyExpressionAxisValue(axis, NormalizedExpressionValue(0.0))
            for axis in BodyExpressionAxis
        ),
        BodyFocusExpressionConstraint(None, None, (), None, None),
        (),
        (),
        (),
        NOW,
    )


def _constraint(revision: int = 1) -> BodyMotionConstraintView:
    return BodyMotionConstraintView(
        "constraint:1",
        BodyMotionConstraintKind.ENVIRONMENT,
        "environment",
        "zone:1",
        revision,
        "trusted boundary",
        ("body:1",),
    )


def _intent() -> BodyMotionIntentView:
    return BodyMotionIntentView(
        "decision:1",
        "intent:1",
        "右手を対象へ向ける",
        "motion:reach",
        "target:1",
        ("constraint:1",),
        ("event:1",),
        REVISIONS,
        ExecutivePriority.FOREGROUND,
        ExecutiveInterruptibility.INTERRUPTIBLE,
        (PreconditionRef("pre:1", "ready", "body", True),),
        (CapabilityRequirement("body", "motion"),),
    )


def _snapshot() -> BodyMotionPlanningContextSnapshot:
    return BodyMotionPlanningContextSnapshot(
        "request:1",
        _intent(),
        _model(),
        _state(),
        _expression(),
        (_constraint(),),
        (
            CapabilityDescriptor(
                "cap:1", "body", ("motion",), CapabilityAvailability.AVAILABLE, 1, {}
            ),
        ),
        NOW,
        "trace:1",
    )


def _goal(effect: BodyMotionEffect = BodyMotionEffect.TRANSLATE) -> BodyMotionGoal:
    target = BodySpatialTarget(BodySpatialTargetKind.TARGET_REF, None, "target:1", 0.5)
    if effect is BodyMotionEffect.IMPULSE:
        target = BodySpatialTarget(BodySpatialTargetKind.DIRECTION, Vector3(0, 1, 0), None, 0.5)
    return BodyMotionGoal(
        "goal:1",
        effect,
        BodyMotionSelector(
            AnatomicalRegion.HAND, AnatomicalSide.RIGHT, ("right_arm",), ("right_hand",)
        ),
        target,
        0.5,
        ("constraint:1",),
    )


def _candidate() -> BodyMotionPlanCandidate:
    goal = _goal()
    return BodyMotionPlanCandidate(
        "candidate:1",
        "request:1",
        "decision:1",
        "intent:1",
        REVISIONS,
        "body.v1",
        2,
        4,
        (_constraint(),),
        (goal,),
        (BodyMotionPhase("phase:1", ("goal:1",), 1.0, BodyBalanceMode.STABLE_SUPPORT_REQUIRED),),
        (),
        (),
        NOW,
    )


def _current() -> BodyMotionPlanningCommitState:
    return BodyMotionPlanningCommitState(
        REVISIONS,
        _intent(),
        _model(),
        _state(),
        _expression(),
        (_constraint(),),
        (
            CapabilityDescriptor(
                "cap:1", "body", ("motion",), CapabilityAvailability.AVAILABLE, 1, {}
            ),
        ),
        (PreconditionRef("pre:1", "ready", "body", True),),
        NOW,
    )


def _candidate_value() -> dict[str, object]:
    return {
        "candidate_id": "candidate:1",
        "request_id": "request:1",
        "source_decision_id": "decision:1",
        "source_intent_id": "intent:1",
        "revisions": REVISIONS.to_dict(),
        "body_model_id": "body.v1",
        "planning_body_state_revision": 2,
        "planning_expression_revision": 4,
        "planning_constraints": [
            {
                "constraint_id": "constraint:1",
                "kind": "environment",
                "source_owner": "environment",
                "source_ref": "zone:1",
                "source_revision": 1,
                "semantic_description": "trusted boundary",
                "subject_refs": ["body:1"],
            }
        ],
        "goals": [
            {
                "goal_id": "goal:1",
                "effect": "translate",
                "selector": {
                    "region": "hand",
                    "side": "right",
                    "chain_ids": ["right_arm"],
                    "end_effector_joint_ids": ["right_hand"],
                },
                "spatial_target": {
                    "kind": "target_ref",
                    "direction": None,
                    "target_ref": "target:1",
                    "extent": 0.5,
                },
                "intensity": 0.5,
                "constraint_refs": ["constraint:1"],
            }
        ],
        "phases": [
            {
                "phase_id": "phase:1",
                "goal_ids": ["goal:1"],
                "relative_duration_weight": 1.0,
                "balance_mode": "stable_support_required",
                "expression_binding_ids": [],
            }
        ],
        "coordination_constraints": [],
        "expression_bindings": [],
    }


@pytest.mark.parametrize(
    "direction",
    [
        Vector3(1, 0, 0),
        Vector3(-1, 0, 0),
        Vector3(0, 1, 0),
        Vector3(0, -1, 0),
        Vector3(0, 0, 1),
        Vector3(0, 0, -1),
    ],
)
def test_direction_accepts_canonical_six_axes(direction: Vector3) -> None:
    assert (
        BodySpatialTarget(BodySpatialTargetKind.DIRECTION, direction, None, 0.5).direction
        == direction
    )


@pytest.mark.parametrize("direction", (Vector3(0, 0, 0), Vector3(1, 1, 0)))
def test_direction_rejects_zero_or_non_unit(direction: Vector3) -> None:
    with pytest.raises(ValueError):
        BodySpatialTarget(BodySpatialTargetKind.DIRECTION, direction, None, 0.5)


def test_contact_and_impulse_structural_invariants_are_fail_closed() -> None:
    with pytest.raises(ValueError):
        BodyMotionGoal(
            "contact",
            BodyMotionEffect.CONTACT,
            BodyMotionSelector(AnatomicalRegion.HAND),
            BodySpatialTarget(BodySpatialTargetKind.TARGET_REF, None, "target:1", 0.5),
            0.5,
        )
    with pytest.raises(ValueError):
        BodyMotionGoal(
            "impulse",
            BodyMotionEffect.IMPULSE,
            BodyMotionSelector(AnatomicalRegion.ROOT),
            BodySpatialTarget(BodySpatialTargetKind.DIRECTION, Vector3(0, 1, 0), None, 0.5),
            0.0,
        )


def test_snapshot_requires_exact_constraint_grounding() -> None:
    with pytest.raises(ValueError):
        replace(_snapshot(), constraints=())


def test_authority_accepts_body_state_and_expression_revision_advance() -> None:
    authority = BodyMotionPlanAuthority()
    plan = authority.commit(
        _candidate(),
        _snapshot(),
        replace(_current(), body_state=replace(_state(), revision=3), expression=_expression(5)),
        plan_id="plan:1",
        committed_at=NOW,
    )
    assert plan.candidate.planning_body_state_revision == 2
    assert plan.candidate.planning_expression_revision == 4


@pytest.mark.parametrize(
    "current",
    [
        replace(_current(), revisions=RevisionVector(8, 5, 3)),
        replace(_current(), revisions=RevisionVector(7, 6, 3)),
        replace(_current(), revisions=RevisionVector(7, 5, 4)),
        replace(_current(), active_intent=None),
        replace(_current(), constraints=(_constraint(2),)),
    ],
)
def test_authority_rejects_hard_stale_sources(current: BodyMotionPlanningCommitState) -> None:
    with pytest.raises(ValueError):
        BodyMotionPlanAuthority().commit(
            _candidate(), _snapshot(), current, plan_id="plan:1", committed_at=NOW
        )


def test_authority_rejects_contact_target_outside_executive_authority() -> None:
    contact = BodyMotionGoal(
        "goal:1",
        BodyMotionEffect.CONTACT,
        BodyMotionSelector(AnatomicalRegion.HAND, AnatomicalSide.RIGHT, (), ("right_hand",)),
        BodySpatialTarget(BodySpatialTargetKind.TARGET_REF, None, "target:2", 0.5),
        0.5,
        ("constraint:1",),
    )
    candidate = replace(
        _candidate(),
        goals=(contact,),
        phases=(
            BodyMotionPhase("phase:1", ("goal:1",), 1.0, BodyBalanceMode.STABLE_SUPPORT_REQUIRED),
        ),
    )
    with pytest.raises(ValueError):
        BodyMotionPlanAuthority().commit(
            candidate, _snapshot(), _current(), plan_id="plan:1", committed_at=NOW
        )


def test_request_contains_expression_context_but_no_raw_input_field() -> None:
    request = build_request(
        _snapshot(),
        trace_id="trace:1",
        created_at=NOW,
        policy=BodyMotionPlanningPolicy(
            make_execution_policy(LLMModelClass.BALANCED, LLMReasoningEffort.MEDIUM, 10, 1, 100)
        ),
    )
    payload = request.input.to_dict()["value"]
    assert isinstance(payload, dict)
    expression = payload["expression"]
    assert isinstance(expression, dict)
    assert expression["revision"] == 4
    assert expression["capture_source_context_revision"] == 7
    assert expression["internal_state_revision"] == 2
    assert expression["attention_revision"] == 3
    assert expression["character_id"] == "generic"
    assert expression["character_definition_revision"] == 1
    assert expression["projection_policy_id"] == "policy"
    assert expression["projection_policy_revision"] == 1
    assert expression["focus"] == {
        "foreground_focus_ref": None,
        "active_focus_intent_ref": None,
        "secondary_monitor_refs": [],
        "current_turn_owner": None,
        "response_obligation": None,
    }
    assert set(tuple(item.items()) for item in expression["axes"]) == {
        (("axis", axis.value), ("value", 0.0)) for axis in BodyExpressionAxis
    }
    assert payload["capabilities"] == [
        {
            "capability_id": "cap:1",
            "capability_type": "body",
            "operations": ["motion"],
            "availability": "available",
            "revision": 1,
            "attributes": {},
        }
    ]
    assert "raw_user_text" not in payload
    assert "character_utterance" not in payload


def test_contract_rejects_duplicate_or_dangling_shape_references() -> None:
    goal = _goal()
    phase = BodyMotionPhase("phase:1", ("goal:1",), 1.0, BodyBalanceMode.STABLE_SUPPORT_REQUIRED)
    with pytest.raises(ValueError):
        DeterministicBodyPlanningDirective((goal, goal), (phase,), (), ())
    with pytest.raises(ValueError):
        DeterministicBodyPlanningDirective(
            (goal,),
            (
                BodyMotionPhase(
                    "phase:1", ("missing",), 1.0, BodyBalanceMode.STABLE_SUPPORT_REQUIRED
                ),
            ),
            (),
            (),
        )


def test_snapshot_requires_a_capability_snapshot_for_the_committed_command() -> None:
    with pytest.raises(ValueError, match="required capability"):
        replace(_snapshot(), capabilities=())


def test_snapshot_keeps_only_descriptors_required_by_the_committed_command() -> None:
    unrelated = CapabilityDescriptor(
        "cap:vision", "vision", ("observe",), CapabilityAvailability.AVAILABLE, 1, {}
    )
    with pytest.raises(ValueError, match="限定"):
        replace(_snapshot(), capabilities=(*_snapshot().capabilities, unrelated))
    no_requirement_intent = replace(_intent(), required_capabilities=())
    with pytest.raises(ValueError, match="限定"):
        replace(_snapshot(), intent=no_requirement_intent)
    assert replace(
        _snapshot(), intent=no_requirement_intent, capabilities=()
    ).capabilities == ()


def test_contract_rejects_duplicate_phase_coordination_and_binding_ids() -> None:
    goal = _goal()
    second = replace(goal, goal_id="goal:2")
    phase = BodyMotionPhase(
        "phase:1", ("goal:1", "goal:2"), 1.0, BodyBalanceMode.STABLE_SUPPORT_REQUIRED
    )
    coordination = BodyCoordinationConstraint(
        "coordination:1", ("goal:1", "goal:2"), BodyCoordinationMode.SYNCHRONIZED
    )
    binding = BodyExpressionBinding("binding:1", BodyExpressionAxis.MOVEMENT_ENERGY, 0.5)
    with pytest.raises(ValueError):
        DeterministicBodyPlanningDirective(
            (goal, second), (phase,), (coordination, coordination), ()
        )
    with pytest.raises(ValueError):
        DeterministicBodyPlanningDirective((goal, second), (phase,), (), (binding, binding))
    with pytest.raises(ValueError):
        DeterministicBodyPlanningDirective(
            (goal,),
            (
                BodyMotionPhase(
                    "phase:1",
                    ("goal:1",),
                    1.0,
                    BodyBalanceMode.STABLE_SUPPORT_REQUIRED,
                    ("missing",),
                ),
            ),
            (),
            (),
        )


@pytest.mark.parametrize(
    "direction",
    (Vector3(1 / 3**0.5, 1 / 3**0.5, 1 / 3**0.5), Vector3(-1 / 2**0.5, 0, 1 / 2**0.5)),
)
def test_direction_accepts_normalized_diagonals(direction: Vector3) -> None:
    assert (
        BodySpatialTarget(BodySpatialTargetKind.DIRECTION, direction, None, 0.5).direction
        == direction
    )


def test_authority_rejects_model_and_live_command_boundary_drift() -> None:
    changed_precondition = (PreconditionRef("pre:1", "ready", "body", False),)
    changed_capability = (
        CapabilityDescriptor(
            "cap:1", "body", ("motion",), CapabilityAvailability.UNAVAILABLE, 2, {}
        ),
    )
    for current in (
        replace(_current(), preconditions=changed_precondition),
        replace(_current(), capabilities=changed_capability),
        replace(
            _current(),
            body_model=replace(_model(), body_model_id="body.v2"),
            body_state=replace(_state(), body_model_id="body.v2"),
        ),
        replace(
            _current(),
            constraints=(replace(_constraint(), semantic_description="different trusted meaning"),),
        ),
    ):
        with pytest.raises(ValueError):
            BodyMotionPlanAuthority().commit(
                _candidate(), _snapshot(), current, plan_id="plan:1", committed_at=NOW
            )


def test_authority_preserves_expression_as_binding_not_baked_axis_value() -> None:
    candidate = replace(
        _candidate(),
        expression_bindings=(
            BodyExpressionBinding("binding:1", BodyExpressionAxis.MOVEMENT_ENERGY, 0.5),
        ),
        phases=(
            BodyMotionPhase(
                "phase:1",
                ("goal:1",),
                1.0,
                BodyBalanceMode.STABLE_SUPPORT_REQUIRED,
                ("binding:1",),
            ),
        ),
    )
    plan = BodyMotionPlanAuthority().commit(
        candidate, _snapshot(), _current(), plan_id="plan:1", committed_at=NOW
    )
    assert plan.candidate.expression_bindings[0].axis is BodyExpressionAxis.MOVEMENT_ENERGY
    assert not hasattr(plan.candidate.expression_bindings[0], "value")


@pytest.mark.asyncio
async def test_separate_deterministic_plans_do_not_wait_on_a_global_planner_lock() -> None:
    entered = 0
    release = asyncio.Event()

    class LiveState:
        async def current_commit_state(
            self, snapshot: BodyMotionPlanningContextSnapshot
        ) -> BodyMotionPlanningCommitState:
            nonlocal entered
            entered += 1
            if entered == 2:
                release.set()
            await release.wait()
            return replace(_current(), active_intent=snapshot.intent)

    directive = DeterministicBodyPlanningDirective(
        _candidate().goals, _candidate().phases, (), ()
    )
    first = replace(_snapshot(), deterministic_directive=directive)
    second = replace(
        first,
        request_id="request:2",
        intent=replace(_intent(), decision_id="decision:2", intent_id="intent:2"),
    )
    planner = DeterministicBodyMotionPlanner(LiveState(), BodyMotionPlanAuthority())
    await asyncio.wait_for(
        asyncio.gather(
            planner.plan(first, candidate_id="candidate:1", plan_id="plan:1", created_at=NOW),
            planner.plan(second, candidate_id="candidate:2", plan_id="plan:2", created_at=NOW),
        ),
        timeout=1,
    )
    assert entered == 2


def test_parser_rejects_unknown_nested_physical_output_and_round_trips() -> None:
    value = _candidate_value()
    assert parse_candidate(value, created_at=NOW) == _candidate()
    cast(dict[str, object], cast(list[object], value["goals"])[0])["joint_angles"] = [0.1]
    with pytest.raises(ValueError, match="goal fields"):
        parse_candidate(value, created_at=NOW)


def test_authority_rejects_unapproved_target_for_all_targeted_effects() -> None:
    unapproved = replace(
        _goal(),
        spatial_target=BodySpatialTarget(BodySpatialTargetKind.TARGET_REF, None, "target:2", 0.5),
    )
    candidate = replace(_candidate(), goals=(unapproved,))
    with pytest.raises(ValueError, match="Executive target"):
        BodyMotionPlanAuthority().commit(
            candidate, _snapshot(), _current(), plan_id="plan:1", committed_at=NOW
        )


def test_authority_rejects_body_model_payload_or_capability_revision_drift() -> None:
    changed_model = CanonicalBodyModel(
        "body.v1",
        _model().joints,
        _model().segments,
        _model().end_effector_joint_ids,
        _model().kinematic_chains,
        _model().center_of_mass,
        reference_height=1.1,
    )
    changed_capability = (
        CapabilityDescriptor("cap:1", "body", ("motion",), CapabilityAvailability.AVAILABLE, 2, {}),
    )
    for current in (
        replace(_current(), body_model=changed_model),
        replace(_current(), capabilities=changed_capability),
    ):
        with pytest.raises(ValueError):
            BodyMotionPlanAuthority().commit(
                _candidate(), _snapshot(), current, plan_id="plan:1", committed_at=NOW
            )


def _decision_and_command() -> tuple[CommittedExecutiveDecision, ExecutiveIntent, SystemCommand]:
    intent = ExecutiveIntent(
        "intent:1",
        ExecutiveIntentKind.BODY,
        "右手を対象へ向ける",
        BodyIntentPayload("motion:reach", "target:1", ("constraint:1",)),
    )
    candidate = ExecutiveDecisionCandidate(
        "candidate:decision",
        "trigger:1",
        ("event:1",),
        7,
        5,
        3,
        ExecutiveOutcome.ACT,
        ExecutivePriority.FOREGROUND,
        ExecutiveInterruptibility.INTERRUPTIBLE,
        (intent,),
        (),
        (),
        ("reason:1",),
        NOW,
    )
    decision = CommittedExecutiveDecision(
        "decision:1", candidate, (), NOW, ExecutiveBoundsProvenance("test-bounds", 1)
    )
    command = SystemCommand(
        "command:1",
        "decision:1",
        IntentRef(IntentKind.BODY, "intent:1"),
        AuthorityRef("executive", "conscious_goal_action", "decision:1"),
        NOW,
        REVISIONS,
        preconditions=(PreconditionRef("pre:1", "ready", "body", True),),
        required_capabilities=(CapabilityRequirement("body", "motion"),),
    )
    return decision, intent, command


def test_executive_binding_copies_only_trusted_command_metadata() -> None:
    from app.domain.body_motion_planning import bind_body_motion_intent

    decision, intent, command = _decision_and_command()
    bound = bind_body_motion_intent(decision, intent, command)
    assert bound.purpose == intent.purpose
    assert bound.priority is decision.candidate.priority
    assert bound.preconditions == command.preconditions
    assert bound.required_capabilities == command.required_capabilities
    with pytest.raises(ValueError):
        bind_body_motion_intent(decision, intent, replace(command, decision_id="decision:2"))
    with pytest.raises(ValueError):
        bind_body_motion_intent(
            decision,
            replace(intent, kind=ExecutiveIntentKind.SPEECH),
            command,
        )


def _policy() -> BodyMotionPlanningPolicy:
    return BodyMotionPlanningPolicy(
        make_execution_policy(LLMModelClass.BALANCED, LLMReasoningEffort.MEDIUM, 10, 1, 100)
    )


def _success(request: LLMRoleRequest) -> LLMRoleResult:
    return LLMRoleResult(
        request.request_id,
        request.role_id,
        LLMRoleStatus.SUCCEEDED,
        request.revisions,
        NOW,
        request.trace_id,
        LLMModelClass.BALANCED,
        1,
        LLMTokenUsage(1, 1),
        StructuredPayload("body.motion-planning.candidate.v1", cast(JsonValue, _candidate_value())),
        started_at=NOW,
    )


@pytest.mark.asyncio
async def test_conditional_llm_path_uses_same_live_authority_gate() -> None:
    class Port:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            return _success(request)

    class LiveState:
        async def current_commit_state(
            self, snapshot: BodyMotionPlanningContextSnapshot
        ) -> BodyMotionPlanningCommitState:
            return _current()

    plan = await BodyMotionPlanner(
        Port(), LiveState(), BodyMotionPlanAuthority(), _policy()
    ).plan(_snapshot(), candidate_id="ignored", plan_id="plan:1", created_at=NOW)
    assert plan.candidate == _candidate()


@pytest.mark.asyncio
async def test_conditional_llm_path_rejects_stale_live_state_before_commit() -> None:
    class Port:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            return _success(request)

    class StaleLiveState:
        async def current_commit_state(
            self, snapshot: BodyMotionPlanningContextSnapshot
        ) -> BodyMotionPlanningCommitState:
            return replace(_current(), revisions=RevisionVector(8, 5, 3))

    with pytest.raises(ValueError, match="stale"):
        await BodyMotionPlanner(
            Port(), StaleLiveState(), BodyMotionPlanAuthority(), _policy()
        ).plan(_snapshot(), candidate_id="ignored", plan_id="plan:1", created_at=NOW)


@pytest.mark.asyncio
async def test_slow_llm_does_not_block_unrelated_deterministic_body_planning() -> None:
    gate = asyncio.Event()

    class DelayedPort:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            await gate.wait()
            return _success(request)

    class LiveState:
        async def current_commit_state(
            self, snapshot: BodyMotionPlanningContextSnapshot
        ) -> BodyMotionPlanningCommitState:
            return replace(_current(), active_intent=snapshot.intent)

    authority = BodyMotionPlanAuthority()
    slow = BodyMotionPlanner(DelayedPort(), LiveState(), authority, _policy())
    slow_task = asyncio.create_task(
        slow.plan(_snapshot(), candidate_id="ignored", plan_id="plan:slow", created_at=NOW)
    )
    await asyncio.sleep(0)
    directive = DeterministicBodyPlanningDirective(_candidate().goals, _candidate().phases, (), ())
    fast_snapshot = replace(
        _snapshot(),
        request_id="request:2",
        intent=replace(_intent(), decision_id="decision:2", intent_id="intent:2"),
        deterministic_directive=directive,
    )
    fast = DeterministicBodyMotionPlanner(LiveState(), authority)
    fast_plan = await asyncio.wait_for(
        fast.plan(fast_snapshot, candidate_id="candidate:2", plan_id="plan:fast", created_at=NOW),
        timeout=1,
    )
    assert fast_plan.plan_id == "plan:fast"
    gate.set()
    await slow_task


def test_authority_rejects_unknown_or_inconsistent_canonical_selector() -> None:
    unknown_chain = replace(
        _goal(),
        selector=BodyMotionSelector(AnatomicalRegion.HAND, AnatomicalSide.RIGHT, ("missing",)),
    )
    inconsistent_effector = replace(
        _goal(),
        selector=BodyMotionSelector(
            AnatomicalRegion.HAND,
            AnatomicalSide.RIGHT,
            ("right_arm",),
            ("root",),
        ),
    )
    wrong_side = replace(
        _goal(),
        selector=BodyMotionSelector(AnatomicalRegion.HAND, AnatomicalSide.LEFT, ("right_arm",)),
    )
    for goal in (unknown_chain, inconsistent_effector, wrong_side):
        with pytest.raises(ValueError):
            BodyMotionPlanAuthority().commit(
                replace(_candidate(), goals=(goal,)),
                _snapshot(),
                _current(),
                plan_id="plan:1",
                committed_at=NOW,
            )


def test_authority_rejects_region_only_selector_absent_from_current_model() -> None:
    absent_region_goal = BodyMotionGoal(
        "goal:1",
        BodyMotionEffect.ORIENT,
        BodyMotionSelector(AnatomicalRegion.FOOT),
        BodySpatialTarget(BodySpatialTargetKind.TARGET_REF, None, "target:1", 0.5),
        0.5,
        ("constraint:1",),
    )
    with pytest.raises(ValueError, match="region/side"):
        BodyMotionPlanAuthority().commit(
            replace(_candidate(), goals=(absent_region_goal,)),
            _snapshot(),
            _current(),
            plan_id="plan:1",
            committed_at=NOW,
        )


def test_authority_grounding_validates_multi_chain_end_effector_coverage() -> None:
    root, right = _model().joints
    left = JointDefinition(
        "left_hand",
        "root",
        AnatomicalRegion.HAND,
        AnatomicalSide.LEFT,
        _transform(),
        (JointLimit(Axis.Z, -1, 1, -0.5, 0.5, 0),),
    )
    model = CanonicalBodyModel(
        "body.v1",
        (root, right, left),
        (
            SegmentDefinition("right_arm", "root", "right_hand", 0.4, 1.0),
            SegmentDefinition("left_arm", "root", "left_hand", 0.4, 1.0),
        ),
        ("right_hand", "left_hand"),
        (
            KinematicChain("right_arm", ("root", "right_hand"), "right_hand"),
            KinematicChain("left_arm", ("root", "left_hand"), "left_hand"),
        ),
        CenterOfMassReference("root", Vector3(0, 0, 0)),
    )
    zero = JointVelocity(Vector3(0, 0, 0), Vector3(0, 0, 0))
    state = BodyState(
        "body.v1",
        2,
        NOW,
        BodyPose(_transform(), (("right_hand", _transform()), ("left_hand", _transform()))),
        BodyVelocity(zero, (("right_hand", zero), ("left_hand", zero))),
    )
    valid = replace(
        _goal(),
        selector=BodyMotionSelector(
            AnatomicalRegion.HAND,
            None,
            ("right_arm", "left_arm"),
            ("right_hand", "left_hand"),
        ),
    )
    snapshot = replace(_snapshot(), body_model=model, body_state=state)
    current = replace(_current(), body_model=model, body_state=state)
    plan = BodyMotionPlanAuthority().commit(
        replace(_candidate(), goals=(valid,)),
        snapshot,
        current,
        plan_id="plan:valid",
        committed_at=NOW,
    )
    assert plan.candidate.goals == (valid,)
    crossed = replace(
        valid,
        selector=BodyMotionSelector(
            AnatomicalRegion.HAND, None, ("right_arm",), ("left_hand",)
        ),
    )
    with pytest.raises(ValueError, match="chain/end-effector"):
        BodyMotionPlanAuthority().commit(
            replace(_candidate(), goals=(crossed,)),
            snapshot,
            current,
            plan_id="plan:crossed",
            committed_at=NOW,
        )


def test_authority_accepts_composed_multi_goal_and_whole_body_motion(
) -> None:
    left_and_right = (
        _goal(),
        replace(_goal(), goal_id="goal:2"),
        BodyMotionGoal(
            "goal:3",
            BodyMotionEffect.IMPULSE,
            BodyMotionSelector(AnatomicalRegion.ROOT, AnatomicalSide.CENTER, (), ()),
            BodySpatialTarget(BodySpatialTargetKind.DIRECTION, Vector3(0, 1, 0), None, 0.5),
            0.8,
            ("constraint:1",),
        ),
    )
    phases = (
        BodyMotionPhase(
            "phase:prepare",
            ("goal:1", "goal:2"),
            1.0,
            BodyBalanceMode.STABLE_SUPPORT_REQUIRED,
        ),
        BodyMotionPhase(
            "phase:impulse",
            ("goal:3",),
            1.0,
            BodyBalanceMode.TEMPORARY_FLIGHT_ALLOWED,
        ),
    )
    candidate = replace(
        _candidate(),
        goals=left_and_right,
        phases=phases,
        coordination_constraints=(
            BodyCoordinationConstraint(
                "coordination:1", ("goal:1", "goal:2"), BodyCoordinationMode.SYNCHRONIZED
            ),
        ),
    )
    before_state = _state()
    plan = BodyMotionPlanAuthority().commit(
        candidate, _snapshot(), _current(), plan_id="plan:1", committed_at=NOW
    )
    assert len(plan.candidate.goals) == 3
    assert len(plan.candidate.phases) == 2
    assert not isinstance(plan, ExecutionResult)
    assert _state() == before_state


def test_authority_accepts_bilateral_motion_with_canonical_left_and_right_chains() -> None:
    root, right = _model().joints
    left = JointDefinition(
        "left_hand",
        "root",
        AnatomicalRegion.HAND,
        AnatomicalSide.LEFT,
        _transform(),
        (JointLimit(Axis.Z, -1, 1, -0.5, 0.5, 0),),
    )
    model = CanonicalBodyModel(
        "body.v1",
        (root, right, left),
        (
            SegmentDefinition("right_arm", "root", "right_hand", 0.4, 1.0),
            SegmentDefinition("left_arm", "root", "left_hand", 0.4, 1.0),
        ),
        ("right_hand", "left_hand"),
        (
            KinematicChain("right_arm", ("root", "right_hand"), "right_hand"),
            KinematicChain("left_arm", ("root", "left_hand"), "left_hand"),
        ),
        CenterOfMassReference("root", Vector3(0, 0, 0)),
    )
    zero = JointVelocity(Vector3(0, 0, 0), Vector3(0, 0, 0))
    state = BodyState(
        "body.v1",
        2,
        NOW,
        BodyPose(_transform(), (("right_hand", _transform()), ("left_hand", _transform()))),
        BodyVelocity(zero, (("right_hand", zero), ("left_hand", zero))),
    )
    right_goal = _goal()
    left_goal = replace(
        right_goal,
        goal_id="goal:left",
        selector=BodyMotionSelector(
            AnatomicalRegion.HAND, AnatomicalSide.LEFT, ("left_arm",), ("left_hand",)
        ),
    )
    candidate = replace(
        _candidate(),
        goals=(right_goal, left_goal),
        phases=(
            BodyMotionPhase(
                "phase:1",
                ("goal:1", "goal:left"),
                1.0,
                BodyBalanceMode.STABLE_SUPPORT_REQUIRED,
            ),
        ),
        coordination_constraints=(
            BodyCoordinationConstraint(
                "coordination:1", ("goal:1", "goal:left"), BodyCoordinationMode.SYNCHRONIZED
            ),
        ),
    )
    snapshot = replace(_snapshot(), body_model=model, body_state=state)
    current = replace(_current(), body_model=model, body_state=state)
    plan = BodyMotionPlanAuthority().commit(
        candidate, snapshot, current, plan_id="plan:bilateral", committed_at=NOW
    )
    assert {goal.selector.side for goal in plan.candidate.goals} == {
        AnatomicalSide.LEFT,
        AnatomicalSide.RIGHT,
    }
