"""目標を改変しない再計画と、置換対象の競合検査を確認する。"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta

import pytest

from app.domain.contracts import CapabilityAvailability
from app.domain.contracts.common import freeze_json
from app.domain.goal_planning import (
    ActivityPlan,
    GoalPlanner,
    GoalPlanningAuthority,
    GoalPlanningCommitState,
    GoalPlanningContextSnapshot,
)
from app.domain.llm import LLMRoleRequest, LLMRoleResult
from tests.domain.goal_planning.test_goal_planning import (
    NOW,
    candidate,
    candidate_json,
    context,
    current,
    policy,
    result_for,
)


def seeded(*, delay: int = 0) -> tuple[GoalPlanningAuthority, ActivityPlan]:
    owner = GoalPlanningAuthority()
    plan = owner.commit(
        candidate(),
        context(),
        current(),
        plan_id="original",
        committed_at=NOW + timedelta(seconds=delay),
    )
    return owner, plan


def test_explicit_replacement_keeps_goal_revision_and_previous_plan() -> None:
    owner, previous = seeded()
    after = owner.commit(
        replace(candidate(), candidate_id="replacement"),
        replace(context(), previous_plan=previous),
        replace(current(), previous_plan=previous),
        plan_id="replacement",
        committed_at=NOW + timedelta(seconds=1),
    )
    assert after.candidate.goal_state_revision == previous.candidate.goal_state_revision
    assert after.candidate.revisions == previous.candidate.revisions
    assert after.supersedes_plan_id == previous.plan_id
    assert owner.current_plan(previous.candidate.goal_id) == after
    assert owner.snapshot(previous.plan_id) == previous
    assert after.to_dict()["supersedes_plan_id"] == previous.plan_id
    assert (
        replace(context(), previous_plan=previous).to_dict()["previous_plan"] == previous.to_dict()
    )
    with pytest.raises(ValueError, match="所有者|Authority"):
        replace(after, supersedes_plan_id="other")


@pytest.mark.parametrize("fault", ["implicit", "missing", "unregistered", "capability", "future"])
def test_failed_replacement_preserves_current_plan(fault: str) -> None:
    owner, previous = seeded(delay=1 if fault == "future" else 0)
    captured = replace(context(), previous_plan=previous)
    live = replace(current(), previous_plan=previous)
    if fault == "implicit":
        captured, live = context(), current()
    elif fault == "missing":
        live = current()
    elif fault == "unregistered":
        other = GoalPlanningAuthority().commit(
            candidate(),
            context(),
            current(),
            plan_id="unregistered",
            committed_at=NOW,
        )
        captured, live = replace(captured, previous_plan=other), replace(live, previous_plan=other)
    elif fault == "capability":
        live = replace(
            live,
            capabilities=(
                replace(
                    live.capabilities[0],
                    availability=CapabilityAvailability.UNAVAILABLE,
                ),
            ),
        )
    with pytest.raises(ValueError):
        owner.commit(candidate(), captured, live, plan_id="replacement", committed_at=NOW)
    assert owner.current_plan(previous.candidate.goal_id) == previous
    assert owner.snapshot("replacement") is None


def test_two_replacements_of_same_plan_commit_at_most_once() -> None:
    owner, previous = seeded()
    captured = replace(context(), previous_plan=previous)
    live = replace(current(), previous_plan=previous)

    def attempt(index: int) -> ActivityPlan | None:
        try:
            return owner.commit(
                candidate(),
                captured,
                live,
                plan_id=f"replacement-{index}",
                committed_at=NOW,
            )
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, (1, 2)))
    successes = [item for item in results if item is not None]
    assert len(successes) == 1
    assert owner.current_plan(previous.candidate.goal_id) == successes[0]
    assert owner.snapshot(previous.plan_id) == previous
    with pytest.raises(ValueError, match="現在の登録済み"):
        owner.commit(candidate(), captured, live, plan_id="late", committed_at=NOW)


@pytest.mark.asyncio
async def test_late_llm_replacement_cannot_replace_new_current_plan() -> None:
    owner, previous = seeded()
    entered, release = asyncio.Event(), asyncio.Event()
    captured = replace(context(deterministic=False), previous_plan=previous)

    class Port:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            assert request.input.value == freeze_json(captured.to_dict())
            entered.set()
            await release.wait()
            return result_for(request, candidate_json())

    class LiveState:
        async def current_state(
            self, snapshot: GoalPlanningContextSnapshot
        ) -> GoalPlanningCommitState:
            return replace(current(), previous_plan=owner.current_plan(snapshot.goal.goal_id))

    planner = GoalPlanner(Port(), LiveState(), owner, policy())
    task = asyncio.create_task(
        planner.plan(
            captured,
            request_id="request-replan",
            trace_id="trace-replan",
            candidate_id="candidate-replan",
            plan_id="late",
            created_at=NOW,
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), 1)
        winner = owner.commit(
            candidate(),
            replace(context(), previous_plan=previous),
            replace(current(), previous_plan=previous),
            plan_id="winner",
            committed_at=NOW,
        )
        release.set()
        with pytest.raises(ValueError, match="判断中に変更"):
            await task
        assert owner.current_plan(previous.candidate.goal_id) == winner
        assert owner.snapshot("late") is None
        assert owner.snapshot(previous.plan_id) == previous
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_simple_replacement_uses_same_gate_without_llm() -> None:
    owner, previous = seeded()
    captured = replace(context(), previous_plan=previous)

    class Port:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            raise AssertionError("単純な計画でLLMを呼び出してはいけません")

    class LiveState:
        async def current_state(
            self, snapshot: GoalPlanningContextSnapshot
        ) -> GoalPlanningCommitState:
            return replace(current(), previous_plan=owner.current_plan(snapshot.goal.goal_id))

    result = await GoalPlanner(Port(), LiveState(), owner, policy()).plan(
        captured,
        request_id="simple-request",
        trace_id="simple-trace",
        candidate_id="simple-candidate",
        plan_id="simple-replacement",
        created_at=NOW,
    )
    assert result.supersedes_plan_id == previous.plan_id
    assert owner.current_plan(previous.candidate.goal_id) == result
    assert owner.snapshot(previous.plan_id) == previous


def test_unrelated_context_revision_does_not_implicitly_replace_existing_plan() -> None:
    owner, previous = seeded()
    captured = context()
    revisions = replace(captured.revisions, goal_revision=5)
    captured = replace(
        captured,
        revisions=revisions,
        goal_context=replace(captured.goal_context, goal_revision=5),
    )
    with pytest.raises(ValueError, match="置換対象を明示"):
        owner.commit(
            replace(candidate(), revisions=revisions),
            captured,
            replace(current(), revisions=revisions),
            plan_id="implicit",
            committed_at=NOW,
        )
    assert owner.current_plan(previous.candidate.goal_id) == previous
