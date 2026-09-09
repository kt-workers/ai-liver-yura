"""計画所有者から判断所有者への承認と、確定失敗時の非更新を確認する。"""

import asyncio
from collections.abc import Iterator
from dataclasses import replace
from datetime import timedelta
from typing import cast

import pytest

from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
from app.domain.contracts import CapabilityAvailability, PreconditionRef
from app.domain.contracts.common import JsonValue
from app.domain.contracts.finalization import FinalizationError
from app.domain.executive import (
    AuthoritativeIntentRequirements,
    ExecutiveCommitState,
    ExecutiveContextSnapshot,
    ExecutiveDecisionCandidate,
    ExecutiveDeliberator,
    ExecutiveIntent,
    ExecutiveIntentKind,
    ExecutiveOutcome,
    ExecutivePreconditionRequirement,
    PlanExecutionIntentPayload,
    PreconditionFact,
    parse_candidate,
    to_system_command,
)
from app.domain.goal_planning import GoalPlanningAuthority
from app.domain.llm import LLMRoleRequest, LLMRoleResult, StructuredPayload
from app.domain.plan_execution.contracts import (
    PlanExecutionAuthorization,
    PlanExecutionPolicy,
    PlanExecutionScope,
    PlanStepExecutionBinding,
)
from app.runtime.kernel.clock import FakeRuntimeClock
from tests.domain.executive.test_executive import (
    REVISIONS,
    candidate,
    live_state,
    policy,
    snapshot,
    success,
)
from tests.domain.goal_planning.test_goal_planning import (
    NOW,
    capability,
)
from tests.domain.goal_planning.test_goal_planning import (
    candidate as plan_candidate,
)
from tests.domain.goal_planning.test_goal_planning import (
    context as plan_context,
)
from tests.domain.goal_planning.test_goal_planning import (
    current as plan_current,
)
from tests.helpers.executive_requirements import capture_plans, fence_clock, make_authority


@pytest.fixture(autouse=True)
def audited_clock() -> Iterator[FakeRuntimeClock]:
    clock = FakeRuntimeClock(NOW)
    with fence_clock(clock.now):
        yield clock


def scope() -> PlanExecutionScope:
    context = plan_context()
    assert REVISIONS.goal_revision is not None
    context = replace(
        context,
        revisions=REVISIONS,
        goal_context=replace(context.goal_context, goal_revision=REVISIONS.goal_revision),
    )
    plan = GoalPlanningAuthority().commit(
        replace(plan_candidate(), revisions=REVISIONS),
        context,
        replace(plan_current(), revisions=REVISIONS),
        plan_id="plan-1",
        committed_at=NOW,
    )
    return PlanExecutionScope(
        "scope-1",
        plan,
        (
            PlanStepExecutionBinding(
                "step-1",
                "collect",
                "target-1",
                {"query": "資料"},
                ("goal-1",),
                (PreconditionRef("pre-ready", "equals", "target-1", True),),
            ),
        ),
        NOW,
        NOW + timedelta(minutes=1),
        PlanExecutionPolicy("plan-execution", 1, 2, 2, 4, 256),
        V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
    )


def inputs() -> tuple[ExecutiveDecisionCandidate, ExecutiveContextSnapshot, ExecutiveCommitState]:
    value = scope()
    intent = ExecutiveIntent(
        "intent-plan",
        ExecutiveIntentKind.PLAN_EXECUTION,
        "承認した範囲の計画を進める",
        PlanExecutionIntentPayload(value.scope_id),
        ("goal-1",),
        value.plan.candidate.steps[0].required_capabilities,
        (ExecutivePreconditionRequirement("pre-ready", True),),
    )
    captured = replace(
        snapshot(),
        plan_scopes=(value,),
        capabilities=(capability(),),
        preconditions=(PreconditionFact("pre-ready", "target-1", "equals", True),),
        captured_at=NOW,
    )
    proposed = replace(candidate(), intents=(intent,), outcome=ExecutiveOutcome.ACT, created_at=NOW)
    current = replace(
        live_state(),
        plan_scopes=(value,),
        capabilities=captured.capabilities,
        preconditions=captured.preconditions,
        requirements=(
            AuthoritativeIntentRequirements(
                intent.intent_id,
                intent.required_capabilities,
                intent.preconditions,
            ),
        ),
    )
    captured = capture_plans(captured)
    assert captured.requirements_generation is not None
    current = captured.requirements_generation.owner.prepare(captured, proposed, current)
    return proposed, captured, current


def test_owner_issues_whole_plan_authorization_and_preserves_serialized_scope() -> None:
    proposed, captured, current = inputs()
    raw = proposed.to_dict()
    raw.pop("created_at")
    assert parse_candidate(raw, captured, created_at=NOW) == proposed
    decision = make_authority(captured).commit(
        proposed,
        captured,
        current=current,
        decision_id="decision-plan",
        committed_at=NOW,
    )
    (authorization,) = decision.plan_authorizations
    assert authorization.scope == captured.plan_scopes[0]
    assert authorization.decision_id == decision.decision_id
    assert authorization.intent_id == proposed.intents[0].intent_id
    assert decision.to_dict()["plan_authorizations"] == [authorization.to_dict()]
    with pytest.raises(ValueError, match="手順へ展開"):
        to_system_command(decision, proposed.intents[0], command_id="command-1")
    with pytest.raises(ValueError, match="意図が対応"):
        replace(decision, plan_authorizations=())
    with pytest.raises(ValueError, match="対象・時刻・方針"):
        replace(decision, committed_at=NOW + timedelta(seconds=1))
    with pytest.raises(ValueError, match="所有者だけ"):
        replace(authorization, authorization_id="forged")


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "changed",
        "capability",
        "condition",
        "expired",
        "unknown_origin",
        "omitted_requirement",
    ],
)
def test_failed_authorization_leaves_trigger_available(fault: str) -> None:
    proposed, captured, current = inputs()
    valid_inputs = proposed, captured, current
    timestamp = NOW
    if fault == "missing":
        current = replace(current, plan_scopes=())
    elif fault == "changed":
        current = replace(
            current,
            plan_scopes=(
                replace(
                    current.plan_scopes[0],
                    deadline_at=NOW + timedelta(seconds=30),
                ),
            ),
        )
    elif fault == "capability":
        current = replace(
            current,
            capabilities=(
                replace(
                    capability(),
                    availability=CapabilityAvailability.UNAVAILABLE,
                ),
            ),
        )
    elif fault == "condition":
        current = replace(current, preconditions=(replace(current.preconditions[0], actual=False),))
    elif fault == "expired":
        timestamp = captured.plan_scopes[0].deadline_at
    elif fault == "unknown_origin":
        captured = replace(
            captured, facts=tuple(f for f in captured.facts if f.fact_id != "goal-1")
        )
    else:
        proposed = replace(
            proposed,
            intents=(
                replace(
                    proposed.intents[0],
                    required_capabilities=(),
                ),
            ),
        )
    authority = make_authority(captured)
    with fence_clock(lambda: timestamp), pytest.raises((ValueError, FinalizationError)):
        authority.commit(
            proposed, captured, current=current, decision_id="decision-plan", committed_at=timestamp
        )
    assert not authority.has_committed(captured.trigger_id)
    proposed, captured, current = valid_inputs
    assert authority.commit(
        proposed, captured, current=current, decision_id="decision-plan", committed_at=NOW
    ).plan_authorizations


def test_scope_cannot_expand_operation_or_arguments_and_authorization_cannot_be_forged() -> None:
    value = scope()
    with pytest.raises(ValueError, match="操作または対象"):
        replace(value, bindings=(replace(value.bindings[0], operation_ref="other"),))
    with pytest.raises(ValueError, match="容量"):
        replace(value, bindings=(replace(value.bindings[0], arguments={"query": "x" * 300}),))
    with pytest.raises(ValueError, match="所有者だけ"):
        PlanExecutionAuthorization("forged", "decision", "intent", value, NOW)


def test_scope_bounds_include_payload_and_existing_facts() -> None:
    value = scope()
    with pytest.raises(ValueError, match="対象全体の容量"):
        replace(
            value,
            bounds_policy=replace(
                value.bounds_policy,
                executive=replace(value.bounds_policy.executive, max_fact_payload_json_bytes=10),
            ),
        )
    with pytest.raises(ValueError, match="識別子が重複"):
        replace(snapshot(), plan_scopes=(replace(value, scope_id="goal-1"),))
    bounded = replace(
        value,
        bounds_policy=replace(
            value.bounds_policy,
            executive=replace(value.bounds_policy.executive, max_fact_refs=1),
        ),
    )
    with pytest.raises(ValueError, match="合計件数"):
        replace(snapshot(), plan_scopes=(bounded,))


@pytest.mark.asyncio
@pytest.mark.parametrize("elapsed", [2, 61])
async def test_authorization_uses_clock_after_live_state_wait(
    elapsed: int,
    audited_clock: FakeRuntimeClock,
) -> None:
    proposed, captured, current = inputs()
    loading = asyncio.Event()
    release = asyncio.Event()
    clock = audited_clock
    authority = make_authority(captured)
    raw = proposed.to_dict()
    raw.pop("created_at")

    class Port:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            return replace(
                success(request),
                completed_at=NOW + timedelta(seconds=1),
                started_at=NOW,
                output=StructuredPayload("executive.candidate.v1", cast(JsonValue, raw)),
            )

    class LiveState:
        async def current_for_commit(
            self,
            context: ExecutiveContextSnapshot,
            candidate: ExecutiveDecisionCandidate,
        ) -> ExecutiveCommitState:
            loading.set()
            await release.wait()
            return current

    deliberator = ExecutiveDeliberator(
        Port(),
        LiveState(),
        policy(),
        authority,
        clock=FakeRuntimeClock(NOW - timedelta(days=1)),
    )
    task = asyncio.create_task(
        deliberator.deliberate(
            captured,
            request_id="request-plan",
            trace_id="trace-plan",
            decision_id="decision-plan",
            created_at=NOW,
        )
    )
    try:
        await asyncio.wait_for(loading.wait(), 1)
        clock.advance(elapsed)
        release.set()
        if elapsed == 61:
            with pytest.raises(FinalizationError, match="TARGET_REJECTED"):
                await task
            assert not authority.has_committed(captured.trigger_id)
        else:
            decision = await task
            assert decision.candidate.created_at == NOW + timedelta(seconds=1)
            assert decision.committed_at == clock.now()
            assert decision.plan_authorizations[0].committed_at == clock.now()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
