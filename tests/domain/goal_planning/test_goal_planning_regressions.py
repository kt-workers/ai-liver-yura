from dataclasses import replace
from datetime import datetime, timezone

import pytest

from app.domain.contracts import (
    CapabilityAvailability,
    CapabilityDescriptor,
    CapabilityRequirement,
    ExecutionStatus,
    RevisionVector,
)
from app.domain.goal_planning import (
    ActivityContextRef,
    ActivityPlanStep,
    GoalPlanningAuthority,
    GoalPlanningCandidate,
    GoalPlanningCommitState,
    GoalPlanningContextSnapshot,
    GoalPlanningOutcome,
    PlanFailurePolicy,
    PlanningBlocker,
    PlanningBlockerKind,
)
from app.domain.goals import (
    GoalContextView,
    GoalKind,
    GoalState,
    GoalStatus,
    InterruptionPolicy,
)

NOW = datetime(2026, 8, 15, tzinfo=timezone.utc)
REVISIONS = RevisionVector(9, 4, 2)


def goal() -> GoalState:
    return GoalState(
        "goal-1",
        GoalKind.ACTIVITY,
        "semantic-goal-1",
        "target-1",
        "decision-1",
        GoalStatus.ACTIVE,
        80,
        ("motivation-1",),
        (),
        ("pre-ready",),
        ("condition-done",),
        InterruptionPolicy.RESUMABLE,
        NOW,
        NOW,
        3,
    )


def capability(
    capability_id: str,
    capability_type: str,
    operations: tuple[str, ...],
) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability_id,
        capability_type,
        operations,
        CapabilityAvailability.AVAILABLE,
        1,
        {},
    )


def research_capability(*operations: str) -> CapabilityDescriptor:
    return capability("cap-research", "research", tuple(operations) or ("collect",))


def step(
    step_id: str,
    operation: str,
    *,
    dependencies: tuple[str, ...] = (),
    resume_activity_id: str | None = None,
    replan_on_failure: bool = False,
) -> ActivityPlanStep:
    return ActivityPlanStep(
        step_id,
        "research",
        operation,
        "target-1",
        resume_activity_id,
        dependencies,
        (CapabilityRequirement("research", operation),),
        ("pre-ready",),
        ("condition-done",),
        InterruptionPolicy.RESUMABLE,
        0,
        replan_on_failure,
    )


def context(
    *,
    capabilities: tuple[CapabilityDescriptor, ...] | None = None,
    requirements: tuple[CapabilityRequirement, ...] | None = None,
    activities: tuple[ActivityContextRef, ...] = (),
    blockers: tuple[PlanningBlocker, ...] = (),
) -> GoalPlanningContextSnapshot:
    item = goal()
    view = GoalContextView(4, "test.goal-context", 1, (item,), (), (), (item,), ())
    bounded_capabilities = capabilities or (research_capability("collect"),)
    planning_requirements = requirements or (CapabilityRequirement("research", "collect"),)
    return GoalPlanningContextSnapshot(
        REVISIONS,
        view,
        item,
        ("event-1",),
        bounded_capabilities,
        planning_requirements,
        activities,
        NOW,
        None,
        blockers,
    )


def candidate(
    *,
    steps: tuple[ActivityPlanStep, ...] | None = None,
    checkpoint_step_ids: tuple[str, ...] = ("step-1",),
    failure_policy: PlanFailurePolicy = PlanFailurePolicy.REPLAN_REQUIRED,
) -> GoalPlanningCandidate:
    planned_steps = steps or (step("step-1", "collect", replan_on_failure=True),)
    return GoalPlanningCandidate(
        "candidate-1",
        "goal-1",
        3,
        ("event-1",),
        REVISIONS,
        GoalPlanningOutcome.PLANNED,
        planned_steps,
        ("condition-done",),
        checkpoint_step_ids,
        failure_policy,
        (),
        NOW,
    )


def current(
    capabilities: tuple[CapabilityDescriptor, ...],
    blockers: tuple[PlanningBlocker, ...] = (),
) -> GoalPlanningCommitState:
    return GoalPlanningCommitState(REVISIONS, goal(), capabilities, blockers)


def test_activity_context_identity_is_inferred_only_when_unambiguous() -> None:
    legacy = ActivityContextRef("activity-1", "goal-1", "collect", ExecutionStatus.STARTED)
    snapshot = context(activities=(legacy,))
    assert snapshot.activities[0].activity_type == "research"
    assert snapshot.activities[0].capability_id == "cap-research"
    assert legacy.activity_type is None
    assert legacy.capability_id is None

    archive = capability("cap-archive", "archive", ("collect",))
    ambiguous = ActivityContextRef("activity-2", "goal-1", "collect", ExecutionStatus.STARTED)
    with pytest.raises(ValueError, match="resolve exactly one"):
        context(
            capabilities=(research_capability("collect"), archive),
            activities=(ambiguous,),
        )


def test_cross_capability_operation_collision_does_not_require_wrong_resume() -> None:
    research = research_capability("collect")
    archive = capability("cap-archive", "archive", ("collect",))
    archive_activity = ActivityContextRef(
        "activity-archive",
        "goal-1",
        "collect",
        ExecutionStatus.STARTED,
        activity_type="archive",
        capability_id="cap-archive",
    )
    snapshot = context(capabilities=(research, archive), activities=(archive_activity,))

    plan = GoalPlanningAuthority().commit(
        candidate(),
        snapshot,
        current((research, archive)),
        plan_id="plan-cross-namespace",
        committed_at=NOW,
    )
    assert plan.candidate.steps[0].resume_activity_id is None

    wrong_resume = replace(
        candidate(),
        steps=(replace(candidate().steps[0], resume_activity_id="activity-archive"),),
    )
    with pytest.raises(ValueError, match="matching nonterminal"):
        GoalPlanningAuthority().commit(
            wrong_resume,
            snapshot,
            current((research, archive)),
            plan_id="plan-wrong-resume",
            committed_at=NOW,
        )

    research_activity = ActivityContextRef(
        "activity-research",
        "goal-1",
        "collect",
        ExecutionStatus.STARTED,
        activity_type="research",
        capability_id="cap-research",
    )
    with pytest.raises(ValueError, match="explicit resume"):
        GoalPlanningAuthority().commit(
            candidate(),
            context(capabilities=(research, archive), activities=(research_activity,)),
            current((research, archive)),
            plan_id="plan-duplicate-research",
            committed_at=NOW,
        )


def test_impossible_can_be_grounded_in_trusted_planning_blocker() -> None:
    blocker = PlanningBlocker(
        "blocker-pre-ready",
        PlanningBlockerKind.PRECONDITION_UNSATISFIED,
        "pre-ready",
    )
    snapshot = context(blockers=(blocker,))
    impossible = replace(
        candidate(),
        outcome=GoalPlanningOutcome.IMPOSSIBLE,
        steps=(),
        completion_condition_refs=(),
        checkpoint_step_ids=(),
        failure_policy=PlanFailurePolicy.FAIL,
        unmet_capabilities=(),
        impossibility_blocker_ids=(blocker.blocker_id,),
    )

    plan = GoalPlanningAuthority().commit(
        impossible,
        snapshot,
        current(snapshot.capabilities, (blocker,)),
        plan_id="plan-blocked",
        committed_at=NOW,
    )
    assert plan.candidate.impossibility_blocker_ids == (blocker.blocker_id,)

    with pytest.raises(ValueError, match="blocker changed"):
        GoalPlanningAuthority().commit(
            impossible,
            snapshot,
            current(snapshot.capabilities),
            plan_id="plan-blocker-resolved",
            committed_at=NOW,
        )

    with pytest.raises(ValueError, match="trusted planning blockers"):
        GoalPlanningAuthority().commit(
            replace(impossible, impossibility_blocker_ids=("invented-blocker",)),
            snapshot,
            current(snapshot.capabilities, (blocker,)),
            plan_id="plan-invented-blocker",
            committed_at=NOW,
        )

    bad_precondition = PlanningBlocker(
        "blocker-bad-precondition",
        PlanningBlockerKind.PRECONDITION_UNSATISFIED,
        "pre-missing",
    )
    with pytest.raises(ValueError, match="outside target goal"):
        context(blockers=(bad_precondition,))

    constraint = PlanningBlocker(
        "blocker-policy",
        PlanningBlockerKind.CONSTRAINT_CONFLICT,
        "constraint-policy-1",
    )
    assert context(blockers=(constraint,)).planning_blockers == (constraint,)


def test_valid_multistep_dag_commits_with_checkpoint_and_recovery() -> None:
    research = research_capability("collect", "analyze", "publish")
    requirements = (
        CapabilityRequirement("research", "collect"),
        CapabilityRequirement("research", "analyze"),
        CapabilityRequirement("research", "publish"),
    )
    steps = (
        step("step-collect", "collect"),
        step("step-analyze", "analyze", dependencies=("step-collect",)),
        step(
            "step-publish",
            "publish",
            dependencies=("step-analyze",),
            replan_on_failure=True,
        ),
    )
    planned = candidate(
        steps=steps,
        checkpoint_step_ids=("step-analyze",),
        failure_policy=PlanFailurePolicy.REPLAN_REQUIRED,
    )
    snapshot = context(capabilities=(research,), requirements=requirements)

    plan = GoalPlanningAuthority().commit(
        planned,
        snapshot,
        current((research,)),
        plan_id="plan-multistep",
        committed_at=NOW,
    )

    assert tuple(item.step_id for item in plan.candidate.steps) == (
        "step-collect",
        "step-analyze",
        "step-publish",
    )
    assert plan.candidate.steps[1].dependency_step_ids == ("step-collect",)
    assert plan.candidate.steps[2].dependency_step_ids == ("step-analyze",)
    assert plan.candidate.checkpoint_step_ids == ("step-analyze",)
    assert plan.candidate.failure_policy is PlanFailurePolicy.REPLAN_REQUIRED
