"""発行済み活動要求を本番の実行調停と事実投影へ渡す。"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.domain.activity_execution import (
    ActivityExecutionAuthority,
    ActivityExecutionCoordinator,
    ActivityExecutionPort,
    ActivityInvocation,
    ExecutionAdapterReport,
    ExecutionCancellationSignal,
    ExecutionDispatchRequest,
    ExecutionPreflightSnapshot,
    to_execution_event,
)
from app.domain.contracts.common import JsonValue

from .body import _project
from .contracts import (
    Gate,
    LabMode,
    ProductionTargetProvenance,
    RunStatus,
    TargetObservation,
    ValidationFixture,
    aware,
)
from .fast_appraisal import EventAppraisalSettings, appraise_and_commit_event
from .runtime import LabTarget, ProductInvocationError, RunContext


@dataclass(frozen=True)
class ActivityLabCase:
    fixture: ValidationFixture
    invocation: ActivityInvocation
    preflight_snapshots: tuple[ExecutionPreflightSnapshot, ...]
    execution_at: datetime
    appraisal: EventAppraisalSettings | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.invocation, ActivityInvocation):
            raise ValueError("発行済みの活動要求が必要です")
        snapshots = tuple(self.preflight_snapshots)
        if not snapshots or any(not isinstance(x, ExecutionPreflightSnapshot) for x in snapshots):
            raise ValueError("各事前確認に返す公開型の状態が必要です")
        object.__setattr__(self, "preflight_snapshots", snapshots)
        if self.appraisal is not None and not isinstance(self.appraisal, EventAppraisalSettings):
            raise ValueError("活動結果の評価設定が不正です")
        aware(self.execution_at)
        if self.execution_at < self.invocation.requested_at:
            raise ValueError("実行時刻を活動要求より前にできません")

    def typed_inputs(self) -> JsonValue:
        return _project(
            {
                "invocation": self.invocation,
                "preflight_snapshots": self.preflight_snapshots,
                "execution_at": self.execution_at,
                "appraisal": None if self.appraisal is None else self.appraisal.typed_inputs(),
            }
        )


class _Preflight:
    def __init__(self, case: ActivityLabCase, context: RunContext) -> None:
        self._case, self._context = case, context
        self.calls = 0

    async def current_for(self, invocation: ActivityInvocation) -> ExecutionPreflightSnapshot:
        if invocation != self._case.invocation or self.calls >= len(self._case.preflight_snapshots):
            raise ValueError("活動の事前確認に対応する検証入力がありません")
        current = self._case.preflight_snapshots[self.calls]
        self.calls += 1

        async def read() -> ExecutionPreflightSnapshot:
            return current

        return await self._context.invoke_port("activity.preflight", read)


class _Clock:
    def __init__(self, at: datetime) -> None:
        self._at = at

    def now(self) -> datetime:
        return self._at


class _ObservedProvider:
    def __init__(self, port: ActivityExecutionPort, context: RunContext) -> None:
        self._port, self._context = port, context

    async def execute(
        self, request: ExecutionDispatchRequest, cancellation: ExecutionCancellationSignal
    ) -> Sequence[ExecutionAdapterReport]:
        return await self._context.invoke_port(
            "activity.provider", lambda: self._port.execute(request, cancellation)
        )


def activity_target(
    cases: tuple[ActivityLabCase, ...],
    port: ActivityExecutionPort,
    provenance: ProductionTargetProvenance,
    contract_revision: str,
    provider_policy_refs: tuple[str, ...],
) -> LabTarget:
    registered = {case.fixture.scenario_id: case for case in cases}
    if len(registered) != len(cases):
        raise ValueError("活動の検証条件は重複できません")

    adjacent = {case.appraisal is not None for case in cases}
    if len(adjacent) > 1:
        raise ValueError("活動の単独検証と評価への隣接検証は別の対象に登録してください")

    async def run(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        case = registered.get(fixture.scenario_id)
        if case is None or case.fixture != fixture or case.typed_inputs() != fixture.typed_inputs:
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        preflight = _Preflight(case, context)
        authority = ActivityExecutionAuthority()
        owner = ActivityExecutionCoordinator(
            preflight, _ObservedProvider(port, context), authority, _Clock(case.execution_at)
        )
        record = await context.invoke_product(
            "activity.execute", lambda: owner.execute(case.invocation)
        )
        event = to_execution_event(
            record,
            event_id=f"{context.run_id}:{context.iteration}:execution",
            trace_id=f"{context.run_id}:{context.iteration}",
        )
        appraisal: JsonValue = None
        status = RunStatus.COMPLETED
        appraisal_failure_stage: str | None = None
        if case.appraisal is not None:
            try:
                appraisal = await appraise_and_commit_event(
                    context,
                    event,
                    case.appraisal,
                    candidate_id=f"{context.run_id}:{context.iteration}:activity-appraisal",
                )
            except ProductInvocationError as error:
                # 後続の状態更新が拒否されても、確定済み活動の事実は保持する。
                status = RunStatus.PRODUCT_FAILED
                appraisal_failure_stage = error.stage
        return TargetObservation(
            status,
            Gate.NOT_RUN,
            _project(
                {
                    "record": record,
                    "event": event,
                    "appraisal": appraisal,
                    "appraisal_failure_stage": appraisal_failure_stage,
                    "preflight_calls": preflight.calls,
                }
            ),
        )

    return LabTarget(
        "activity_execution",
        contract_revision,
        frozenset({LabMode.ADJACENT if True in adjacent else LabMode.ISOLATION}),
        provider_policy_refs,
        provenance,
        run,
        frozenset({"activity.preflight", "activity.provider"}),
    )
