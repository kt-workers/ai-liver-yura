"""実行の確定事実に基づく完了評価と、誤った評価の非確定を確認する。"""

from collections.abc import Iterator
from dataclasses import replace
from datetime import timedelta

import pytest

from app.domain.activity_execution import (
    ActivityExecutionAuthority,
    ActivityInterruptibility,
    ActivityInvocation,
    ExecutionAdapterReport,
    ExecutionPreconditionState,
    ExecutionPreflightSnapshot,
)
from app.domain.contracts import AuthorityRef, ExecutionStatus, IntentKind, IntentRef, SystemCommand
from app.domain.contracts.finalization import FinalizationError
from app.domain.executive import (
    AuthoritativeIntentRequirements,
    ExecutiveCommitState,
    ExecutiveContextSnapshot,
    ExecutiveDecisionCandidate,
    ExecutiveIntent,
    ExecutiveIntentKind,
    ExecutiveOutcome,
    PlanProgressIntentPayload,
    parse_candidate,
    to_system_command,
)
from app.domain.plan_execution.progress_contracts import (
    PlanExecutionObservation,
    PlanProgressContext,
    PlanStepCompletionClaim,
)
from tests.domain.executive.test_executive import REVISIONS
from tests.domain.executive.test_plan_authorization import inputs
from tests.domain.goal_planning.test_goal_planning import NOW
from tests.helpers.executive_requirements import capture_plans, fence_clock, make_authority


@pytest.fixture(autouse=True)
def audited_progress_clock() -> Iterator[None]:
    with fence_clock(lambda: NOW + timedelta(seconds=2)):
        yield


def progress_inputs(
    status: ExecutionStatus = ExecutionStatus.COMPLETED,
) -> tuple[ExecutiveDecisionCandidate, ExecutiveContextSnapshot, ExecutiveCommitState]:
    proposed, captured, current = inputs()
    with fence_clock(lambda: NOW):
        approved = (
            make_authority(captured)
            .commit(
                proposed,
                captured,
                current=current,
                decision_id="decision-plan",
                committed_at=NOW,
            )
            .plan_authorizations[0]
        )
    binding = approved.scope.bindings[0]
    invocation = ActivityInvocation(
        "invocation-1",
        SystemCommand(
            "command-1",
            approved.decision_id,
            IntentRef(IntentKind.ACTIVITY, approved.intent_id),
            AuthorityRef("executive", "conscious_goal_action", approved.decision_id),
            NOW,
            REVISIONS,
            preconditions=binding.preconditions,
            required_capabilities=approved.scope.plan.candidate.steps[0].required_capabilities,
        ),
        binding.operation_ref,
        binding.arguments,
        ActivityInterruptibility.INTERRUPTIBLE,
        NOW,
        binding.target_ref,
    )
    owner = ActivityExecutionAuthority()
    preflight = ExecutionPreflightSnapshot(
        REVISIONS,
        captured.capabilities,
        (ExecutionPreconditionState("pre-ready", "target-1", "equals", True),),
        NOW,
    )
    owner.admit(invocation, preflight)
    record = owner.start("command-1", preflight, NOW, "dispatch-1").record
    if status is not ExecutionStatus.STARTED:
        record = owner.apply_report(
            ExecutionAdapterReport(
                "command-1",
                "invocation-1",
                "dispatch-1",
                status,
                NOW + timedelta(seconds=1),
                {},
            )
        ).record
    context = PlanProgressContext(
        "progress-1",
        approved,
        (PlanExecutionObservation("step-1", 1, record),),
    )
    intent = ExecutiveIntent(
        "intent-progress",
        ExecutiveIntentKind.PLAN_PROGRESS,
        "手順の完了条件を評価する",
        PlanProgressIntentPayload(
            context.context_id,
            (PlanStepCompletionClaim("step-1", ("condition-done",), ("command-1",)),),
        ),
        ("goal-1",),
    )
    proposed = replace(
        proposed,
        intents=(intent,),
        outcome=ExecutiveOutcome.CONTINUE_ACTIVITY,
        created_at=NOW + timedelta(seconds=2),
    )
    captured = replace(
        captured, plan_scopes=(), plan_progress_contexts=(context,), captured_at=proposed.created_at
    )
    current = replace(
        current,
        plan_scopes=(),
        plan_progress_contexts=(context,),
        requirements=(AuthoritativeIntentRequirements(intent.intent_id, (), ()),),
    )
    captured = capture_plans(captured)
    assert captured.requirements_generation is not None
    current = captured.requirements_generation.owner.prepare(captured, proposed, current)
    return proposed, captured, current


def test_progress_assessment_uses_actual_execution_without_new_execution_authorization() -> None:
    proposed, captured, current = progress_inputs()
    raw = proposed.to_dict()
    raw.pop("created_at")
    assert parse_candidate(raw, captured, created_at=proposed.created_at) == proposed
    assessment_time = NOW + timedelta(seconds=2)
    decision = make_authority(captured).commit(
        proposed,
        captured,
        current=current,
        decision_id="decision-progress",
        committed_at=proposed.created_at,
    )
    assert (
        decision.committed_at
        == assessment_time
        == decision.plan_progress_assessments[0].committed_at
    )
    assert not decision.plan_authorizations
    (assessment,) = decision.plan_progress_assessments
    assert assessment.context == captured.plan_progress_contexts[0]
    assert decision.to_dict()["plan_progress_assessments"] == [assessment.to_dict()]
    assert isinstance(proposed.intents[0].payload, PlanProgressIntentPayload)
    assert assessment.claims == proposed.intents[0].payload.claims
    with pytest.raises(ValueError, match="直接変換"):
        to_system_command(decision, proposed.intents[0], command_id="extra-command")
    with pytest.raises(ValueError, match="所有者だけ"):
        replace(assessment, decision_id="forged")
    with pytest.raises(ValueError, match="意図が対応"):
        replace(decision, plan_progress_assessments=())


@pytest.mark.parametrize(
    "fault",
    ["missing", "changed", "unexecuted", "failed", "running", "condition", "evidence", "time"],
)
def test_invalid_assessment_never_consumes_decision_trigger(fault: str) -> None:
    status = {
        "failed": ExecutionStatus.FAILED,
        "running": ExecutionStatus.STARTED,
    }.get(fault, ExecutionStatus.COMPLETED)
    proposed, captured, current = progress_inputs(status)
    if fault == "missing":
        current = replace(current, plan_progress_contexts=())
    elif fault == "changed":
        current = replace(
            current,
            plan_progress_contexts=(
                replace(
                    current.plan_progress_contexts[0],
                    observations=(),
                ),
            ),
        )
    elif fault in {"unexecuted", "condition", "evidence"}:
        payload = proposed.intents[0].payload
        assert isinstance(payload, PlanProgressIntentPayload)
        claim = payload.claims[0]
        if fault == "unexecuted":
            claim = replace(claim, step_id="not-executed")
        elif fault == "condition":
            claim = replace(claim, condition_refs=("different-condition",))
        else:
            claim = replace(claim, evidence_refs=("condition-done",))
        proposed = replace(
            proposed,
            intents=(
                replace(
                    proposed.intents[0],
                    payload=replace(payload, claims=(claim,)),
                ),
            ),
        )
    timestamp = NOW if fault == "time" else proposed.created_at
    owner = make_authority(captured)
    with fence_clock(lambda: timestamp), pytest.raises((ValueError, FinalizationError)):
        owner.commit(
            proposed,
            captured,
            current=current,
            decision_id="decision-progress",
            committed_at=timestamp,
        )
    assert not owner.has_committed(captured.trigger_id)
    proposed, captured, current = progress_inputs()
    assert owner.requirements_owner is not None and captured.requirements_generation is not None
    generation = captured.requirements_generation
    owner.requirements_owner.publish(
        generation.policy, tuple(replace(source, revision=2) for source in generation.sources)
    )
    captured = owner.requirements_owner.capture(captured)
    current = owner.requirements_owner.prepare(captured, proposed, current)
    assert owner.commit(
        proposed,
        captured,
        current=current,
        decision_id="decision-progress",
        committed_at=proposed.created_at,
    ).plan_progress_assessments


def test_progress_observation_rejects_wrong_target_and_excess_attempt() -> None:
    _, captured, _ = progress_inputs()
    context = captured.plan_progress_contexts[0]
    observation = context.observations[0]
    with pytest.raises(ValueError, match="承認済み"):
        replace(context, observations=(replace(observation, attempt=3),))
    with pytest.raises(ValueError, match="承認済み"):
        replace(
            context,
            observations=(
                replace(
                    observation,
                    record=replace(
                        observation.record,
                        invocation=replace(
                            observation.record.invocation,
                            target_ref="wrong-target",
                        ),
                    ),
                ),
            ),
        )
    assert observation.record.invocation.to_dict()["target_ref"] == "target-1"
    with pytest.raises(ValueError, match="識別子が重複"):
        replace(captured, plan_progress_contexts=(replace(context, context_id="goal-1"),))


def test_progress_context_rejects_future_observation_and_combined_fact_overflow() -> None:
    _, captured, _ = progress_inputs()
    context = captured.plan_progress_contexts[0]
    with pytest.raises(ValueError, match="未来"):
        replace(captured, captured_at=NOW)
    with pytest.raises(ValueError, match="合計件数"):
        replace(
            captured,
            facts=captured.facts * 0
            + tuple(
                replace(captured.facts[0], fact_id=f"fact-{index}")
                for index in range(
                    context.authorization.scope.bounds_policy.executive.max_fact_refs
                )
            ),
        )
    with pytest.raises(ValueError, match="型付き"):
        replace(context, observations=("not-an-observation",))  # type: ignore[arg-type]


def test_completion_claim_references_are_counted_in_candidate_bounds() -> None:
    from app.domain.executive import validate_candidate_bounds

    proposed, captured, _ = progress_inputs()
    bounds = captured.plan_progress_contexts[0].authorization.scope.bounds_policy.executive
    with pytest.raises(ValueError, match="intent reference"):
        validate_candidate_bounds(proposed, replace(bounds, max_refs_per_intent=2))
    payload = proposed.intents[0].payload
    assert isinstance(payload, PlanProgressIntentPayload)
    assert set(payload.reference_ids()) == {
        "progress-1",
        "step-1",
        "condition-done",
        "command-1",
    }
