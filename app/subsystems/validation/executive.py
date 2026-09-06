"""既存の実行判断入口を呼び、採用済み判断を検証証拠へ記録する。"""

from dataclasses import dataclass
from datetime import datetime

from app.domain.contracts.common import JsonValue, freeze_json
from app.domain.executive import (
    ExecutiveContextSnapshot,
    ExecutiveDecisionAuthority,
    ExecutiveDeliberator,
    ExecutiveLiveStatePort,
    ExecutivePolicy,
)
from app.domain.executive.deliberator import build_request
from app.usecases.ports.llm import LLMRolePort

from .contracts import (
    Gate,
    LabMode,
    ProductionTargetProvenance,
    RunStatus,
    TargetObservation,
    ValidationFixture,
)
from .llm_port import LabLLMPortFactory, ObservedLLMRolePort, resolve_port
from .runtime import LabTarget, RunContext


@dataclass(frozen=True)
class ExecutiveLabCase:
    fixture: ValidationFixture
    snapshot: ExecutiveContextSnapshot
    created_at: datetime

    def typed_inputs(self, policy: ExecutivePolicy) -> JsonValue:
        return build_request(
            self.snapshot,
            request_id="fixture",
            trace_id="fixture",
            created_at=self.created_at,
            policy=policy,
        ).input.value


def executive_target(
    cases: tuple[ExecutiveLabCase, ...],
    port: LLMRolePort | LabLLMPortFactory,
    live_state: ExecutiveLiveStatePort,
    policy: ExecutivePolicy,
    provenance: ProductionTargetProvenance,
    contract_revision: str,
    provider_policy_refs: tuple[str, ...],
) -> LabTarget:
    registered = {case.fixture.scenario_id: case for case in cases}
    if len(registered) != len(cases):
        raise ValueError("実行判断の検証条件は重複できません")

    async def run(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        case = registered.get(fixture.scenario_id)
        if (
            case is None
            or case.fixture != fixture
            or case.typed_inputs(policy) != fixture.typed_inputs
        ):
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        prefix = f"{context.run_id}:{fixture.scenario_id}:{context.iteration}"
        request = build_request(
            case.snapshot,
            request_id=prefix,
            trace_id=prefix,
            created_at=case.created_at,
            policy=policy,
        )
        owner = ExecutiveDeliberator(
            ObservedLLMRolePort(
                context, resolve_port(port, context), {request.role_id: "executive.llm"}
            ),
            live_state,
            policy,
            ExecutiveDecisionAuthority(),
        )
        result = await context.invoke_product(
            "executive.deliberate",
            lambda: owner.deliberate(
                case.snapshot,
                request_id=prefix,
                trace_id=prefix,
                decision_id=f"{prefix}:decision",
                created_at=case.created_at,
            ),
        )
        return TargetObservation(RunStatus.COMPLETED, Gate.NOT_RUN, freeze_json(result.to_dict()))

    return LabTarget(
        "executive",
        contract_revision,
        frozenset({LabMode.ISOLATION}),
        provider_policy_refs,
        provenance,
        run,
        frozenset({"executive.llm"}),
        frozenset({"executive.llm"}),
    )
