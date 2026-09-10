"""確定済み意味Ownerの束縛を、値を変えず既存実行契約へ投影する。"""

from datetime import datetime

from app.domain.activity_execution import (
    ActivityExecutionAuthority,
    ActivityInterruptibility,
    ActivityInvocation,
)
from app.domain.contracts import PreconditionRef
from app.domain.contracts.finalization import authority_read_set
from app.domain.executive.contracts import (
    ActivityIntentPayload,
    CommittedExecutiveDecision,
    ExecutiveIntent,
)
from app.domain.executive.projector import to_system_command
from app.domain.goal_planning import ActivityPlan, GoalPlanningAuthority
from app.domain.plan_execution.contracts import PlanStepExecutionBinding
from app.domain.plan_execution.owner import PlanArgumentFact


def direct_invocation(
    decision: CommittedExecutiveDecision,
    intent: ExecutiveIntent,
    *,
    command_id: str,
    invocation_id: str,
    requested_at: datetime,
) -> ActivityInvocation:
    if intent not in decision.candidate.intents or not isinstance(
        intent.payload, ActivityIntentPayload
    ):
        raise ValueError("確定判断のACTIVITY意図が必要です")
    publications = [
        p for p in decision.activity_bindings if p.value.binding_id == intent.payload.binding_ref
    ]
    if len(publications) != 1:
        raise ValueError("確定判断の正規bindingが存在しません")
    pub = publications[0]
    pub.require_current()
    value = pub.value
    return ActivityInvocation(
        invocation_id,
        to_system_command(decision, intent, command_id=command_id),
        value.operation_ref,
        value.arguments,
        ActivityInterruptibility(decision.candidate.interruptibility.value),
        requested_at,
        value.target_ref,
    )


def plan_execution_inputs(
    plan: ActivityPlan,
    planning: GoalPlanningAuthority,
    preconditions: tuple[PreconditionRef, ...],
    *,
    activities: ActivityExecutionAuthority | None = None,
) -> tuple[tuple[PlanStepExecutionBinding, ...], tuple[PlanArgumentFact, ...]]:
    pubs = {p.value.binding_id: p for p in plan.activity_bindings}
    participants = (
        planning.finalization_participant,
        *(t._participant for p in pubs.values() for t in p.tokens),
    )
    if activities is not None:
        participants = (*participants, activities.finalization_participant)
    with authority_read_set(participants):
        if planning.current_plan(plan.candidate.goal_id) != plan:
            raise ValueError("現在の確定計画と一致しません")
        conditions = {p.precondition_id: p for p in preconditions}
        if len(conditions) != len(preconditions) or set(conditions) != {
            c for step in plan.candidate.steps for c in step.precondition_ids
        }:
            raise ValueError("計画の前提条件の集合が一致しません")
        bindings = []
        facts: dict[str, PlanArgumentFact] = {}
        for step in plan.candidate.steps:
            if step.binding_ref not in pubs:
                raise ValueError("手順の確定bindingがありません")
            pub = pubs[step.binding_ref]
            pub.require_current()
            value = pub.value
            resumed = None
            if step.resume_activity_id is not None:
                record = (
                    None if activities is None else activities.snapshot(step.resume_activity_id)
                )
                if record is None or record.terminal:
                    raise ValueError("既存実行の再開にはActivity Ownerの非終端要求照合が必要です")
                resumed = record.invocation
            bindings.append(
                PlanStepExecutionBinding(
                    step.step_id,
                    value.operation_ref,
                    value.target_ref,
                    value.arguments,
                    tuple(f.reference_id for f in value.sources),
                    tuple(conditions[c] for c in step.precondition_ids),
                    resumed,
                )
            )
            for source in value.sources:
                fact = PlanArgumentFact(source.reference_id, source.revision, source.value)
                if source.reference_id in facts and facts[source.reference_id] != fact:
                    raise ValueError("手順間で同じ由来の内容が異なります")
                facts[source.reference_id] = fact
        return tuple(bindings), tuple(facts.values())
