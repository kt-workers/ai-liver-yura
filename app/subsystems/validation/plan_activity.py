"""計画承認・活動・実行事実の還流を本体の公開入口から観測する。"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from weakref import WeakKeyDictionary

from app.bootstrap import MinimumCoreApplication
from app.domain.activity_execution import (
    ActivityExecutionPort,
    ActivityExecutionRecord,
    ExecutionAdapterReport,
    ExecutionCancellationSignal,
    ExecutionDispatchRequest,
    ExecutionEffectUncertainty,
)
from app.domain.brain_integration import BrainIntegrationWork, BrainWorkAdmission, BrainWorkStatus
from app.domain.contracts import ExecutionStatus, PreconditionRef
from app.domain.contracts.common import JsonValue
from app.domain.executive import CommittedExecutiveDecision
from app.domain.input_gateway import InputAdmission, InputAdmissionStatus
from app.domain.plan_execution.contracts import PlanExecutionScope
from app.domain.plan_execution.owner import PlanExecutionProgress
from app.runtime.kernel import RuntimeClock

from .body import _project
from .cognition import _IterationApplication, _result_projection, _status
from .contracts import (
    Gate,
    InjectedFailure,
    LabMode,
    ProductionTargetProvenance,
    RunStatus,
    TargetObservation,
    ValidationFixture,
    aware,
    identifier,
)
from .runtime import LabTarget, RunContext


@dataclass(frozen=True)
class PlanActivityLabCase:
    """正規入力と、同じ製品Ownerが採用済みの計画への参照だけを登録する。"""

    fixture: ValidationFixture
    admission: InputAdmission
    goal_id: str | None = None
    plan_id: str | None = None
    preconditions: tuple[PreconditionRef, ...] = ()
    deadline_at: datetime | None = None

    def __post_init__(self) -> None:
        selected = (self.goal_id, self.plan_id, self.deadline_at)
        if any(value is not None for value in selected):
            if any(value is None for value in selected):
                raise ValueError("計画参照にはGoal・計画・期限をすべて指定してください")
            assert self.goal_id is not None and self.plan_id is not None
            assert self.deadline_at is not None
            identifier(self.goal_id)
            identifier(self.plan_id)
            aware(self.deadline_at)
        elif self.preconditions:
            raise ValueError("計画参照なしで前提条件を指定できません")
        object.__setattr__(self, "preconditions", tuple(self.preconditions))

    def typed_inputs(self) -> JsonValue:
        return _project(
            {
                "admission": self.admission,
                "goal_id": self.goal_id,
                "plan_id": self.plan_id,
                "preconditions": self.preconditions,
                "deadline_at": self.deadline_at,
            }
        )


class ObservedActivityPort:
    """trusted factoryで製品adapterを包み、提供先境界の遅延を観測する。"""

    def __init__(
        self, port: ActivityExecutionPort, context: RunContext, clock: RuntimeClock
    ) -> None:
        self._port, self._context, self._clock = port, context, clock

    async def execute(
        self, request: ExecutionDispatchRequest, cancellation: ExecutionCancellationSignal
    ) -> Sequence[ExecutionAdapterReport]:
        async def execute() -> Sequence[ExecutionAdapterReport]:
            failure = self._context.take_failure("plan_activity.provider")
            if failure is None:
                return await self._port.execute(request, cancellation)
            status = {
                InjectedFailure.PROVIDER_UNAVAILABLE: ExecutionStatus.FAILED,
                InjectedFailure.TIMEOUT: ExecutionStatus.TIMED_OUT,
                InjectedFailure.CANCELLED: ExecutionStatus.CANCELLED,
            }[failure]
            invocation = request.invocation
            return (
                ExecutionAdapterReport(
                    invocation.command.command_id,
                    invocation.invocation_id,
                    request.dispatch_id,
                    status,
                    self._clock.now(),
                    {"injected_failure": failure.value},
                    effect_uncertainty=ExecutionEffectUncertainty.UNKNOWN,
                ),
            )

        return await self._context.invoke_port("plan_activity.provider", execute)


@dataclass(frozen=True)
class CommittedActivityLabCase:
    """同じ製品Ownerで確定した判断をBrain-Cの公開配送入口へ渡す。"""

    fixture: ValidationFixture
    work: BrainIntegrationWork
    decision: CommittedExecutiveDecision

    def typed_inputs(self) -> JsonValue:
        return _project({"envelope": self.work.envelope, "decision": self.decision.to_dict()})


def plan_activity_target(
    cases: tuple[PlanActivityLabCase | CommittedActivityLabCase, ...],
    application_factory: Callable[[RunContext], MinimumCoreApplication],
    provenance: ProductionTargetProvenance,
    contract_revision: str,
    provider_policy_refs: tuple[str, ...],
    *,
    provenance_source: Callable[[], ProductionTargetProvenance],
) -> LabTarget:
    """step選択・命令生成・完了評価を製品へ委譲し、実際のtraceを最後まで追う。"""
    registered = {case.fixture.scenario_id: case for case in cases}
    if len(registered) != len(cases) or not callable(application_factory):
        raise ValueError("計画・活動の検証条件または起動factoryが不正です")
    if not callable(provenance_source):
        raise ValueError("現在の製品来歴を取得する入口が必要です")
    ownership: WeakKeyDictionary[RunContext, _IterationApplication] = WeakKeyDictionary()

    async def run(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        case = registered.get(fixture.scenario_id)
        if case is None or case.fixture != fixture or case.typed_inputs() != fixture.typed_inputs:
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        if isinstance(case, PlanActivityLabCase) and (
            case.admission.status is not InputAdmissionStatus.ACCEPTED
            or case.admission.event is None
        ):
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        actual = provenance_source()
        if not isinstance(actual, ProductionTargetProvenance):
            raise ValueError("現在の製品来歴の公開型が不正です")
        if actual != provenance:
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        owner = ownership.get(context)
        if owner is None:
            owner = _IterationApplication()
            ownership[context] = owner
            context.add_cleanup("plan_activity.stop", owner.stop)
        if owner.current is not None:
            raise ValueError("前iterationのアプリケーションが未停止です")
        app = application_factory(context)
        if not isinstance(app, MinimumCoreApplication):
            raise ValueError("factoryは正規MinimumCoreApplicationを返す必要があります")
        owner.current = app
        if app.cognition is None or app.cognition.execution is None:
            await owner.stop()
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        delivery = app.cognition.execution
        if isinstance(case, PlanActivityLabCase):
            assert case.admission.event is not None
            event = case.admission.event.envelope
            trace_id, root_id = event.trace_id, event.event_id
        else:
            trace_id = case.work.envelope.trace_id
            root_id = case.work.envelope.root_trigger_id or case.work.envelope.trigger_id
        scope = None
        if isinstance(case, PlanActivityLabCase) and case.goal_id is not None:
            plan = delivery.planning.current_plan(case.goal_id)
            if plan is None or plan.plan_id != case.plan_id:
                await owner.stop()
                return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
            assert case.deadline_at is not None

            async def prepare() -> PlanExecutionScope:
                assert isinstance(case, PlanActivityLabCase)
                assert case.deadline_at is not None and plan is not None
                return delivery.prepare_plan(
                    plan,
                    case.preconditions,
                    deadline_at=case.deadline_at,
                    source_event_id=event.event_id,
                )

            scope = await context.invoke_product("plan_activity.prepare_plan", prepare)
        await context.invoke_product("plan_activity.start", app.start)

        async def submit() -> BrainWorkAdmission | None:
            assert app.cognition is not None
            if isinstance(case, CommittedActivityLabCase):
                delivery.accept_decision(case.work, case.decision)
                return None
            return app.cognition.submit_input(case.admission)

        accepted = await context.invoke_product("plan_activity.submit_input", submit)
        if accepted is not None and not accepted.accepted:
            await owner.stop()
            return TargetObservation(
                RunStatus.PRODUCT_FAILED, Gate.FAIL, _project({"admission": accepted})
            )
        try:
            app.brain.trace(trace_id)
        except KeyError:
            await owner.stop()
            return TargetObservation(
                RunStatus.PRODUCT_FAILED, Gate.FAIL, _project({"admission": accepted})
            )
        observed: set[str] = set()
        outputs: list[JsonValue] = []
        decisions: list[CommittedExecutiveDecision] = []
        records: dict[str, ActivityExecutionRecord] = {}
        status = RunStatus.COMPLETED
        # 公開outcomeより先に製品が後続workを登録するため、未観測の実traceで終端を判定する。
        # 固定段数や「活動成功なら計画完了」というLab独自の判断は持たない。
        for _ in range(context.policy.max_intervals):
            outcome = await context.invoke_product("plan_activity.outcome", app.brain.next_outcome)
            trace = app.brain.trace(trace_id)
            if (
                outcome.trace_id != trace_id
                or outcome.work_id in observed
                or outcome.work_id not in {i.work_id for i in trace.intervals}
            ):
                raise ValueError("計画・活動の公開outcomeとtraceが一致しません")
            observed.add(outcome.work_id)
            result = outcome.result
            command_ids = (
                result.command_ids
                if isinstance(result, PlanExecutionProgress)
                else (result.result.command_id,)
                if isinstance(result, ActivityExecutionRecord)
                else ()
            )
            for command_id in command_ids:
                record = app.activities.snapshot(command_id)
                if record is not None:
                    records[command_id] = record
            if isinstance(result, CommittedExecutiveDecision):
                decisions.append(result)
            projected = (
                _project(result)
                if isinstance(result, (ActivityExecutionRecord, PlanExecutionProgress))
                else _result_projection(result)
            )
            outputs.append(
                _project(
                    {
                        "work_id": outcome.work_id,
                        "module": outcome.module,
                        "lane": outcome.lane,
                        "status": outcome.status,
                        "completed_at": outcome.completed_at,
                        "result": projected,
                    }
                )
            )
            current_status = _status(outcome.status, result)
            if status is RunStatus.COMPLETED and current_status is not RunStatus.COMPLETED:
                status = current_status
            if observed == {i.work_id for i in trace.intervals}:
                break
        trace = app.brain.trace(trace_id)
        structural = (
            bool(decisions)
            and status is RunStatus.COMPLETED
            and trace.root_trigger_id == root_id
            and observed == {i.work_id for i in trace.intervals}
            and all(i.status is BrainWorkStatus.COMPLETED for i in trace.intervals)
        )
        if status is RunStatus.COMPLETED and not structural:
            status = RunStatus.PRODUCT_FAILED
        await context.invoke_product("plan_activity.stop", owner.stop)
        return TargetObservation(
            status,
            Gate.PASS if structural else Gate.FAIL,
            _project(
                {
                    "admission": accepted,
                    "scope": None if scope is None else scope.to_dict(),
                    "outcomes": outputs,
                    "execution_records": tuple(records.values()),
                    "trace": trace,
                }
            ),
        )

    return LabTarget(
        "plan_activity",
        contract_revision,
        frozenset({LabMode.INTEGRATED}),
        provider_policy_refs,
        provenance,
        run,
        frozenset({"plan_activity.provider"}),
        frozenset({"plan_activity.provider"}),
    )
