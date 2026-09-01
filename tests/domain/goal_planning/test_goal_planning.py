import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import cast

import pytest

from app.domain.contracts import (
    CapabilityAvailability,
    CapabilityDescriptor,
    CapabilityRequirement,
    ExecutionStatus,
    RevisionVector,
)
from app.domain.contracts.common import JsonValue
from app.domain.goal_planning import (
    ActivityContextRef,
    ActivityPlan,
    ActivityPlanStep,
    DeterministicPlanningDirective,
    GoalPlanner,
    GoalPlanningAuthority,
    GoalPlanningCandidate,
    GoalPlanningCommitState,
    GoalPlanningContextSnapshot,
    GoalPlanningOutcome,
    GoalPlanningPolicy,
    PlanFailurePolicy,
    build_request,
    commit_result,
    parse_candidate,
)
from app.domain.goals import (
    GoalContextView,
    GoalKind,
    GoalState,
    GoalStatus,
    InterruptionPolicy,
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


def capability(*, revision: int = 1, degraded: bool = False) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        "cap-research",
        "research",
        ("collect",),
        CapabilityAvailability.DEGRADED if degraded else CapabilityAvailability.AVAILABLE,
        revision,
        {},
    )


def step(*, dependency_step_ids: tuple[str, ...] = ()) -> ActivityPlanStep:
    return ActivityPlanStep(
        "step-1",
        "research",
        "collect",
        "target-1",
        None,
        dependency_step_ids,
        (CapabilityRequirement("research", "collect"),),
        ("pre-ready",),
        ("condition-done",),
        InterruptionPolicy.RESUMABLE,
        1,
        True,
    )


def directive() -> DeterministicPlanningDirective:
    return DeterministicPlanningDirective(
        GoalPlanningOutcome.PLANNED,
        (step(),),
        ("condition-done",),
        ("step-1",),
        PlanFailurePolicy.REPLAN_REQUIRED,
    )


def context(*, deterministic: bool = True) -> GoalPlanningContextSnapshot:
    item = goal()
    view = GoalContextView(4, "test.goal-context", 1, (item,), (), (), (item,), ())
    return GoalPlanningContextSnapshot(
        REVISIONS,
        view,
        item,
        ("event-1",),
        (capability(),),
        (CapabilityRequirement("research", "collect"),),
        (),
        NOW,
        directive() if deterministic else None,
    )


def candidate() -> GoalPlanningCandidate:
    return GoalPlanningCandidate(
        "candidate-1",
        "goal-1",
        3,
        ("event-1",),
        REVISIONS,
        GoalPlanningOutcome.PLANNED,
        (step(),),
        ("condition-done",),
        ("step-1",),
        PlanFailurePolicy.REPLAN_REQUIRED,
        (),
        NOW,
    )


def current(**changes: object) -> GoalPlanningCommitState:
    values = {
        "revisions": REVISIONS,
        "goal": goal(),
        "capabilities": (capability(),),
        **changes,
    }
    return GoalPlanningCommitState(**values)  # type: ignore[arg-type]


def policy() -> GoalPlanningPolicy:
    return GoalPlanningPolicy(
        make_execution_policy(LLMModelClass.BALANCED, LLMReasoningEffort.MEDIUM, 10, 1, 1200)
    )


def candidate_json() -> dict[str, object]:
    value = candidate().to_dict()
    value.pop("created_at")
    return value


def result_for(request: LLMRoleRequest, value: object) -> LLMRoleResult:
    return LLMRoleResult(
        request.request_id,
        request.role_id,
        LLMRoleStatus.SUCCEEDED,
        request.revisions,
        NOW + timedelta(seconds=2),
        request.trace_id,
        LLMModelClass.BALANCED,
        1,
        LLMTokenUsage(10, 10),
        StructuredPayload("yura.goal-planning.candidate.v1", cast(JsonValue, value)),
        started_at=NOW + timedelta(seconds=1),
    )


def test_contracts_are_immutable_and_plan_requires_authority() -> None:
    raw = [step()]
    planned = DeterministicPlanningDirective(
        GoalPlanningOutcome.PLANNED,
        cast(tuple[ActivityPlanStep, ...], raw),
        ("condition-done",),
        (),
        PlanFailurePolicy.REPLAN_REQUIRED,
    )
    raw.clear()
    assert len(planned.steps) == 1
    with pytest.raises(ValueError, match="GoalPlanningAuthority"):
        ActivityPlan("plan-1", candidate(), NOW)
    committed = GoalPlanningAuthority().commit(
        candidate(), context(), current(), plan_id="plan-1", committed_at=NOW
    )
    with pytest.raises(ValueError, match="GoalPlanningAuthority"):
        replace(committed, candidate=replace(candidate(), candidate_id="forged"))


def test_snapshot_requires_exact_active_goal_and_revision() -> None:
    item = context()
    with pytest.raises(ValueError, match="active goal"):
        replace(item, goal=replace(goal(), status=GoalStatus.SUSPENDED))
    with pytest.raises(ValueError, match="goal context revision"):
        replace(item, revisions=RevisionVector(9, 5, 2))


def test_plan_shape_rejects_dangling_cycle_and_nonplanned_payload() -> None:
    with pytest.raises(ValueError, match="outside candidate"):
        replace(candidate(), steps=(step(dependency_step_ids=("missing",)),))
    second = replace(step(), step_id="step-2", dependency_step_ids=("step-1",))
    first = replace(step(), dependency_step_ids=("step-2",))
    with pytest.raises(ValueError, match="acyclic"):
        replace(candidate(), steps=(first, second), checkpoint_step_ids=())
    with pytest.raises(ValueError, match="non-planned"):
        replace(candidate(), outcome=GoalPlanningOutcome.IMPOSSIBLE)
    no_plan = replace(
        candidate(),
        outcome=GoalPlanningOutcome.NO_PLAN_REQUIRED,
        steps=(),
        completion_condition_refs=(),
        checkpoint_step_ids=(),
        failure_policy=PlanFailurePolicy.FAIL,
        unmet_capabilities=(),
    )
    assert no_plan.outcome is GoalPlanningOutcome.NO_PLAN_REQUIRED
    impossible = replace(
        no_plan,
        outcome=GoalPlanningOutcome.IMPOSSIBLE,
        unmet_capabilities=(CapabilityRequirement("missing", "operate"),),
    )
    assert impossible.outcome is GoalPlanningOutcome.IMPOSSIBLE


def test_no_plan_requires_trusted_directive_and_impossible_requires_live_absence() -> None:
    no_plan_directive = DeterministicPlanningDirective(
        GoalPlanningOutcome.NO_PLAN_REQUIRED,
        (),
        (),
        (),
        PlanFailurePolicy.FAIL,
    )
    no_plan_context = replace(context(), deterministic_directive=no_plan_directive)
    no_plan_candidate = replace(
        candidate(),
        outcome=GoalPlanningOutcome.NO_PLAN_REQUIRED,
        steps=(),
        completion_condition_refs=(),
        checkpoint_step_ids=(),
        failure_policy=PlanFailurePolicy.FAIL,
        unmet_capabilities=(),
    )
    plan = GoalPlanningAuthority().commit(
        no_plan_candidate,
        no_plan_context,
        current(),
        plan_id="plan-no-plan",
        committed_at=NOW,
    )
    assert plan.candidate.outcome is GoalPlanningOutcome.NO_PLAN_REQUIRED
    with pytest.raises(ValueError, match="trusted deterministic"):
        GoalPlanningAuthority().commit(
            no_plan_candidate,
            replace(no_plan_context, deterministic_directive=None),
            current(),
            plan_id="plan-untrusted-no-plan",
            committed_at=NOW,
        )

    missing = CapabilityRequirement("missing", "operate")
    impossible = replace(
        no_plan_candidate,
        outcome=GoalPlanningOutcome.IMPOSSIBLE,
        unmet_capabilities=(missing,),
    )
    impossible_context = replace(
        context(),
        planning_requirements=(missing,),
        deterministic_directive=None,
    )
    GoalPlanningAuthority().commit(
        impossible,
        impossible_context,
        current(),
        plan_id="plan-impossible",
        committed_at=NOW,
    )
    available_missing = CapabilityDescriptor(
        "cap-missing",
        "missing",
        ("operate",),
        CapabilityAvailability.AVAILABLE,
        1,
        {},
    )
    with pytest.raises(ValueError, match="became available"):
        GoalPlanningAuthority().commit(
            impossible,
            impossible_context,
            current(capabilities=(capability(), available_missing)),
            plan_id="plan-not-impossible",
            committed_at=NOW,
        )
    irrelevant = replace(
        impossible,
        unmet_capabilities=(CapabilityRequirement("irrelevant", "invented"),),
    )
    with pytest.raises(ValueError, match="trusted requirements"):
        GoalPlanningAuthority().commit(
            irrelevant,
            impossible_context,
            current(),
            plan_id="plan-irrelevant-impossible",
            committed_at=NOW,
        )


def test_deterministic_candidate_cannot_diverge_from_trusted_directive() -> None:
    divergent = replace(
        candidate(),
        checkpoint_step_ids=(),
    )
    with pytest.raises(ValueError, match="deterministic directive"):
        GoalPlanningAuthority().commit(
            divergent,
            context(),
            current(),
            plan_id="plan-divergent",
            committed_at=NOW,
        )


def test_authority_rejects_goal_and_reference_changes() -> None:
    owner = GoalPlanningAuthority()
    with pytest.raises(ValueError, match="target"):
        owner.commit(
            replace(candidate(), steps=(replace(step(), target_ref="other"),)),
            context(),
            current(),
            plan_id="plan-target",
            committed_at=NOW,
        )
    with pytest.raises(ValueError, match="precondition"):
        owner.commit(
            replace(candidate(), steps=(replace(step(), precondition_ids=("unknown",)),)),
            context(),
            current(),
            plan_id="plan-pre",
            committed_at=NOW,
        )


def test_nonterminal_activity_requires_explicit_resume_reference() -> None:
    activity = ActivityContextRef("activity-1", "goal-1", "collect", ExecutionStatus.STARTED)
    active_context = replace(context(), activities=(activity,), deterministic_directive=None)
    with pytest.raises(ValueError, match="explicit resume"):
        GoalPlanningAuthority().commit(
            candidate(),
            active_context,
            current(),
            plan_id="plan-duplicate-activity",
            committed_at=NOW,
        )
    resumed = replace(step(), resume_activity_id="activity-1")
    plan = GoalPlanningAuthority().commit(
        replace(candidate(), steps=(resumed,)),
        active_context,
        current(),
        plan_id="plan-resume",
        committed_at=NOW,
    )
    assert plan.candidate.steps[0].resume_activity_id == "activity-1"


def test_missing_degraded_unknown_and_stale_capability_fail_closed() -> None:
    owner = GoalPlanningAuthority()
    with pytest.raises(ValueError, match="unavailable"):
        owner.commit(
            candidate(),
            replace(context(), capabilities=()),
            current(),
            plan_id="p1",
            committed_at=NOW,
        )
    with pytest.raises(ValueError, match="unavailable"):
        replace(context(), capabilities=(capability(degraded=True),))
    with pytest.raises(ValueError, match="changed"):
        owner.commit(
            candidate(),
            context(),
            current(capabilities=(capability(revision=2),)),
            plan_id="p3",
            committed_at=NOW,
        )


def test_all_revision_and_goal_state_staleness_are_rejected() -> None:
    for revisions in (
        RevisionVector(10, 4, 2),
        RevisionVector(9, 5, 2),
        RevisionVector(9, 4, 3),
    ):
        with pytest.raises(ValueError, match="stale"):
            GoalPlanningAuthority().commit(
                candidate(),
                context(),
                current(revisions=revisions),
                plan_id=f"plan-{revisions.to_dict()}",
                committed_at=NOW,
            )
    with pytest.raises(ValueError, match="target goal changed"):
        GoalPlanningAuthority().commit(
            candidate(),
            context(),
            current(goal=replace(goal(), status=GoalStatus.ABANDONED, revision=4)),
            plan_id="plan-goal-stale",
            committed_at=NOW,
        )


def test_same_goal_revision_commit_is_atomic() -> None:
    owner = GoalPlanningAuthority()

    def commit(index: int) -> str:
        try:
            owner.commit(
                replace(candidate(), candidate_id=f"candidate-{index}"),
                context(),
                current(),
                plan_id=f"plan-{index}",
                committed_at=NOW,
            )
            return "committed"
        except ValueError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(commit, (1, 2)))
    assert sorted(results) == ["committed", "rejected"]


def test_parse_candidate_is_strict_and_round_trips() -> None:
    parsed = parse_candidate(candidate_json(), created_at=NOW)
    assert parsed == candidate()
    bad = candidate_json()
    bad["execution_completed"] = True
    with pytest.raises(ValueError, match="fields"):
        parse_candidate(bad, created_at=NOW)
    bad_step = candidate_json()
    cast(list[dict[str, object]], bad_step["steps"])[0]["joint_angles"] = [1, 2]
    with pytest.raises(ValueError, match="step fields"):
        parse_candidate(bad_step, created_at=NOW)


def test_llm_exchange_and_request_snapshot_are_revalidated() -> None:
    item = context(deterministic=False)
    request = build_request(
        item, request_id="request-1", trace_id="trace-1", created_at=NOW, policy=policy()
    )
    plan = commit_result(
        request,
        result_for(request, candidate_json()),
        snapshot=item,
        current=current(),
        authority=GoalPlanningAuthority(),
        plan_id="plan-1",
        policy=policy(),
    )
    assert plan.candidate.outcome is GoalPlanningOutcome.PLANNED
    with pytest.raises(ValueError):
        commit_result(
            request,
            result_for(request, candidate_json()),
            snapshot=replace(item, capabilities=()),
            current=current(),
            authority=GoalPlanningAuthority(),
            plan_id="plan-2",
            policy=policy(),
        )


class FakeLiveState:
    def __init__(self) -> None:
        self.calls = 0

    async def current_state(self, snapshot: GoalPlanningContextSnapshot) -> GoalPlanningCommitState:
        self.calls += 1
        return GoalPlanningCommitState(snapshot.revisions, snapshot.goal, snapshot.capabilities)


class FailingPort:
    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
        raise AssertionError("simple path must not invoke LLM")


class DelayedPort:
    def __init__(self, gate: asyncio.Event) -> None:
        self.gate = gate

    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
        await self.gate.wait()
        return result_for(request, candidate_json())


@pytest.mark.asyncio
async def test_simple_path_skips_llm() -> None:
    live = FakeLiveState()
    plan = await GoalPlanner(FailingPort(), live, GoalPlanningAuthority(), policy()).plan(
        context(),
        request_id="unused-request",
        trace_id="trace-1",
        candidate_id="candidate-simple",
        plan_id="plan-simple",
        created_at=NOW,
    )
    assert plan.candidate.candidate_id == "candidate-simple"
    assert live.calls == 1


@pytest.mark.asyncio
async def test_slow_complex_planning_does_not_block_unrelated_simple_plan() -> None:
    gate = asyncio.Event()
    owner = GoalPlanningAuthority()
    slow = GoalPlanner(DelayedPort(gate), FakeLiveState(), owner, policy())
    slow_task = asyncio.create_task(
        slow.plan(
            context(deterministic=False),
            request_id="request-slow",
            trace_id="trace-slow",
            candidate_id="candidate-unused",
            plan_id="plan-slow",
            created_at=NOW,
        )
    )
    await asyncio.sleep(0)
    other_context = replace(
        context(),
        goal=replace(goal(), goal_id="goal-2"),
        goal_context=replace(
            context().goal_context,
            active_goals=(replace(goal(), goal_id="goal-2"),),
            recently_changed_goals=(replace(goal(), goal_id="goal-2"),),
        ),
        deterministic_directive=directive(),
    )
    other = GoalPlanner(FailingPort(), FakeLiveState(), owner, policy())
    other_plan = await asyncio.wait_for(
        other.plan(
            other_context,
            request_id="unused",
            trace_id="trace-other",
            candidate_id="candidate-other",
            plan_id="plan-other",
            created_at=NOW,
        ),
        timeout=0.2,
    )
    assert other_plan.candidate.goal_id == "goal-2"
    gate.set()
    await slow_task


@pytest.mark.asyncio
async def test_cancelled_complex_planning_never_commits() -> None:
    gate = asyncio.Event()
    owner = GoalPlanningAuthority()
    task = asyncio.create_task(
        GoalPlanner(DelayedPort(gate), FakeLiveState(), owner, policy()).plan(
            context(deterministic=False),
            request_id="request-cancel",
            trace_id="trace-cancel",
            candidate_id="unused",
            plan_id="plan-cancel",
            created_at=NOW,
        )
    )
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert owner.snapshot("plan-cancel") is None
