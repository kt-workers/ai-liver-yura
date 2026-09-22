"""入力意味解析の既存公開入口をそのまま利用する単独検証接続。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.contracts.common import freeze_json
from app.domain.input_gateway import NormalizedInputEvent
from app.domain.input_meaning import (
    InputMeaningInterpretationResult,
    InputMeaningInterpreter,
    InputMeaningLiveContextPort,
    InputMeaningPolicy,
    ReferenceContext,
    build_request,
)
from app.domain.llm import LLMRoleStatus
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
from .meaning_appraisal import MeaningAppraisalBindings, MeaningAppraisalSettings, appraise_meaning
from .runtime import LabTarget, RunContext


@dataclass(frozen=True)
class InputMeaningLabCase:
    fixture: ValidationFixture
    event: NormalizedInputEvent
    reference_context: ReferenceContext
    created_at: datetime
    appraisal: MeaningAppraisalSettings | None = None


def input_meaning_target(
    cases: tuple[InputMeaningLabCase, ...],
    port: LLMRolePort | LabLLMPortFactory,
    live_context: InputMeaningLiveContextPort,
    policy: InputMeaningPolicy,
    provenance: ProductionTargetProvenance,
    contract_revision: str,
    provider_policy_refs: tuple[str, ...],
    *,
    appraisal_bindings: MeaningAppraisalBindings | None = None,
) -> LabTarget:
    adjacent = appraisal_bindings is not None
    if any((case.appraisal is not None) != adjacent for case in cases):
        raise ValueError("深い状況評価の検証条件と接続指定が一致しません")
    executive = appraisal_bindings is not None and appraisal_bindings.executive is not None
    if any(
        (case.appraisal is not None and case.appraisal.executive is not None) != executive
        for case in cases
    ):
        raise ValueError("実行判断の検証条件と接続指定が一致しません")
    stages = {"input_meaning.llm"}
    if adjacent:
        stages.add("appraisal.llm")
    if executive:
        stages.add("executive.llm")
    registered = {case.fixture.scenario_id: case for case in cases}
    if len(registered) != len(cases):
        raise ValueError("入力意味解析の検証条件は重複できません")

    async def run(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        case = registered.get(fixture.scenario_id)
        if case is None or case.fixture != fixture:
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        request_id = f"{context.run_id}:{fixture.scenario_id}:{context.iteration}"
        trace_id = case.event.envelope.trace_id
        request = build_request(
            case.event,
            case.reference_context,
            request_id=request_id,
            trace_id=trace_id,
            created_at=case.created_at,
            policy=policy,
        )
        expected = request.input.value
        if case.appraisal is not None:
            expected = freeze_json(
                {
                    "input_meaning": expected,
                    "appraisal": case.appraisal.typed_inputs(),
                }
            )
        if expected != freeze_json(fixture.typed_inputs):
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        result = await InputMeaningInterpreter(
            ObservedLLMRolePort(
                context, resolve_port(port, context), {request.role_id: "input_meaning.llm"}
            ),
            live_context,
            policy,
        ).interpret(
            case.event,
            case.reference_context,
            request_id=request_id,
            trace_id=trace_id,
            created_at=case.created_at,
        )
        status = input_meaning_run_status(result)
        if case.appraisal is not None and appraisal_bindings is not None:
            appraisal = None
            if result.meaning is not None:
                appraisal = await appraise_meaning(
                    context, case.event.envelope, result.meaning, case.appraisal, appraisal_bindings
                )
            return TargetObservation(
                status,
                Gate.NOT_RUN,
                freeze_json(
                    {
                        "input_meaning": result.to_dict(),
                        "appraisal": appraisal,
                    }
                ),
            )
        return TargetObservation(status, Gate.NOT_RUN, freeze_json(result.to_dict()))

    return LabTarget(
        "meaning_appraisal" if adjacent else "input_meaning",
        contract_revision,
        frozenset({LabMode.ADJACENT if adjacent else LabMode.ISOLATION}),
        provider_policy_refs,
        provenance,
        run,
        frozenset(stages),
        frozenset(stages),
    )


def input_meaning_run_status(result: InputMeaningInterpretationResult) -> RunStatus:
    """入力意味の公開された型付き失敗を、既存Lab分類へ写す。"""
    status = RunStatus.COMPLETED
    if result.role_failure is not None:
        status = {
            LLMRoleStatus.TIMED_OUT: RunStatus.TIMED_OUT,
            LLMRoleStatus.CANCELLED: RunStatus.CANCELLED,
        }.get(result.role_status or LLMRoleStatus.FAILED, RunStatus.PROVIDER_FAILED)
    elif result.boundary_failure is not None:
        status = RunStatus.BLOCKED_UPSTREAM
    return status
