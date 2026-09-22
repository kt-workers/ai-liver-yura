"""目標計画・発話意味の既存入口を使い、確定した計画を記録する。"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Generic, TypeVar

from app.domain.contracts.common import JsonValue, freeze_json
from app.domain.goal_planning import (
    GoalPlanner,
    GoalPlanningAuthority,
    GoalPlanningBoundsPolicyPort,
    GoalPlanningContextSnapshot,
    GoalPlanningLiveStatePort,
    GoalPlanningPolicy,
)
from app.domain.speech_semantics import (
    SpeechSemanticAuthority,
    SpeechSemanticBoundsPolicyPort,
    SpeechSemanticContextSnapshot,
    SpeechSemanticsLiveStatePort,
    SpeechSemanticsPlanner,
    SpeechSemanticsPolicy,
)
from app.usecases.ports.llm import LLMRolePort

from .contracts import (
    Gate,
    LabMode,
    ProductionTargetProvenance,
    RunStatus,
    TargetObservation,
    ValidationFixture,
    aware,
)
from .llm_port import LabLLMPortFactory, ObservedLLMRolePort, resolve_port
from .runtime import LabTarget, RunContext

T = TypeVar("T", GoalPlanningContextSnapshot, SpeechSemanticContextSnapshot)


@dataclass(frozen=True)
class PlanningLabCase(Generic[T]):
    fixture: ValidationFixture
    snapshot: T
    created_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(
            self.snapshot, (GoalPlanningContextSnapshot, SpeechSemanticContextSnapshot)
        ):
            raise ValueError("計画の製品入力が不正です")
        aware(self.created_at)

    def typed_inputs(self) -> JsonValue:
        return freeze_json(
            {"snapshot": self.snapshot.to_dict(), "created_at": self.created_at.isoformat()}
        )


def _target(
    module: str,
    cases: tuple[PlanningLabCase[T], ...],
    invoke: Callable[[RunContext, PlanningLabCase[T], str], Awaitable[JsonValue]],
    provenance: ProductionTargetProvenance,
    contract_revision: str,
    provider_policy_refs: tuple[str, ...],
) -> LabTarget:
    registered = {case.fixture.scenario_id: case for case in cases}
    if len(registered) != len(cases):
        raise ValueError("計画の検証条件は重複できません")

    async def run(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        case = registered.get(fixture.scenario_id)
        if case is None or case.fixture != fixture or case.typed_inputs() != fixture.typed_inputs:
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        prefix = f"{context.run_id}:{fixture.scenario_id}:{context.iteration}"
        result = await invoke(context, case, prefix)
        return TargetObservation(RunStatus.COMPLETED, Gate.NOT_RUN, result)

    stages = frozenset({f"{module}.llm"})
    return LabTarget(
        module,
        contract_revision,
        frozenset({LabMode.ISOLATION}),
        provider_policy_refs,
        provenance,
        run,
        stages,
        stages,
    )


def goal_planning_target(
    cases: tuple[PlanningLabCase[GoalPlanningContextSnapshot], ...],
    port: LLMRolePort | LabLLMPortFactory,
    live_state: GoalPlanningLiveStatePort,
    policy: GoalPlanningPolicy,
    provenance: ProductionTargetProvenance,
    contract_revision: str,
    provider_policy_refs: tuple[str, ...],
    *,
    bounds_state: GoalPlanningBoundsPolicyPort | None = None,
) -> LabTarget:
    async def invoke(
        context: RunContext, case: PlanningLabCase[GoalPlanningContextSnapshot], prefix: str
    ) -> JsonValue:
        owner = GoalPlanner(
            ObservedLLMRolePort(
                context, resolve_port(port, context), {"goal_planning": "goal_planning.llm"}
            ),
            live_state,
            GoalPlanningAuthority(),
            policy,
            bounds_state,
        )
        result = await context.invoke_product(
            "goal_planning.plan",
            lambda: owner.plan(
                case.snapshot,
                request_id=prefix,
                trace_id=prefix,
                candidate_id=f"{prefix}:candidate",
                plan_id=f"{prefix}:plan",
                created_at=case.created_at,
            ),
        )
        return freeze_json(result.to_dict())

    return _target(
        "goal_planning", cases, invoke, provenance, contract_revision, provider_policy_refs
    )


def speech_semantics_target(
    cases: tuple[PlanningLabCase[SpeechSemanticContextSnapshot], ...],
    port: LLMRolePort | LabLLMPortFactory,
    live_state: SpeechSemanticsLiveStatePort,
    policy: SpeechSemanticsPolicy,
    provenance: ProductionTargetProvenance,
    contract_revision: str,
    provider_policy_refs: tuple[str, ...],
    *,
    bounds_state: SpeechSemanticBoundsPolicyPort | None = None,
) -> LabTarget:
    async def invoke(
        context: RunContext, case: PlanningLabCase[SpeechSemanticContextSnapshot], prefix: str
    ) -> JsonValue:
        owner = SpeechSemanticsPlanner(
            ObservedLLMRolePort(
                context, resolve_port(port, context), {"speech_semantics": "speech_semantics.llm"}
            ),
            live_state,
            SpeechSemanticAuthority(),
            policy,
            bounds_state,
        )
        result = await context.invoke_product(
            "speech_semantics.plan",
            lambda: owner.plan(
                case.snapshot,
                request_id=prefix,
                trace_id=prefix,
                candidate_id=f"{prefix}:candidate",
                plan_id=f"{prefix}:plan",
                created_at=case.created_at,
            ),
        )
        return freeze_json(result.to_dict())

    return _target(
        "speech_semantics", cases, invoke, provenance, contract_revision, provider_policy_refs
    )
