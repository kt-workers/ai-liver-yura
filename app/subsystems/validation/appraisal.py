"""既存の深い状況評価入口を呼び、状態変更候補を記録する。"""

from dataclasses import dataclass
from datetime import datetime

from app.domain.appraisal import (
    DeepAppraisalContext,
    DeepAppraisalInterpreter,
    DeepAppraisalLiveStatePort,
    DeepAppraisalPolicy,
    InternalStateSnapshot,
    build_deep_request,
)
from app.domain.contracts import EventEnvelope
from app.domain.contracts.common import JsonValue, freeze_json
from app.domain.input_meaning import StructuredInputMeaning
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
class AppraisalLabCase:
    fixture: ValidationFixture
    event: EventEnvelope
    meaning: StructuredInputMeaning | None
    state: InternalStateSnapshot
    context: DeepAppraisalContext
    created_at: datetime

    def typed_inputs(self, policy: DeepAppraisalPolicy) -> JsonValue:
        return build_deep_request(
            self.event,
            self.meaning,
            self.state,
            self.context,
            request_id="fixture",
            trace_id="fixture",
            created_at=self.created_at,
            policy=policy,
        ).input.value


def appraisal_target(
    cases: tuple[AppraisalLabCase, ...],
    port: LLMRolePort | LabLLMPortFactory,
    live_state: DeepAppraisalLiveStatePort,
    policy: DeepAppraisalPolicy,
    provenance: ProductionTargetProvenance,
    contract_revision: str,
    provider_policy_refs: tuple[str, ...],
) -> LabTarget:
    registered = {case.fixture.scenario_id: case for case in cases}
    if len(registered) != len(cases):
        raise ValueError("状況評価の検証条件は重複できません")

    async def run(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        case = registered.get(fixture.scenario_id)
        if (
            case is None
            or case.fixture != fixture
            or case.typed_inputs(policy) != fixture.typed_inputs
        ):
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        prefix = f"{context.run_id}:{fixture.scenario_id}:{context.iteration}"
        request = build_deep_request(
            case.event,
            case.meaning,
            case.state,
            case.context,
            request_id=prefix,
            trace_id=prefix,
            created_at=case.created_at,
            policy=policy,
        )
        owner = DeepAppraisalInterpreter(
            ObservedLLMRolePort(
                context, resolve_port(port, context), {request.role_id: "appraisal.llm"}
            ),
            live_state,
            policy,
        )
        result = await context.invoke_product(
            "appraisal.appraise",
            lambda: owner.appraise(
                case.event,
                case.meaning,
                case.state,
                case.context,
                request_id=prefix,
                trace_id=prefix,
                created_at=case.created_at,
            ),
        )
        return TargetObservation(RunStatus.COMPLETED, Gate.NOT_RUN, freeze_json(result.to_dict()))

    return LabTarget(
        "appraisal",
        contract_revision,
        frozenset({LabMode.ISOLATION}),
        provider_policy_refs,
        provenance,
        run,
        frozenset({"appraisal.llm"}),
        frozenset({"appraisal.llm"}),
    )
