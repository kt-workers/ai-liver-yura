"""通常認知の本番配送を実行し、公開された結果とtraceだけを観測する。"""

from collections.abc import Callable
from dataclasses import dataclass
from weakref import WeakKeyDictionary

from app.bootstrap import MinimumCoreApplication
from app.domain.appraisal import AppraisalStateCommit
from app.domain.brain_integration import BrainIntegrationModule, BrainWorkStatus
from app.domain.contracts.common import JsonValue
from app.domain.executive import CommittedExecutiveDecision
from app.domain.input_gateway import InputAdmission, InputAdmissionStatus
from app.domain.input_meaning import InputMeaningInterpretationResult

from .body import _project
from .contracts import (
    Gate,
    LabMode,
    ProductionTargetProvenance,
    RunStatus,
    TargetObservation,
    ValidationFixture,
)
from .input_meaning import input_meaning_run_status
from .runtime import LabTarget, RunContext


@dataclass(frozen=True)
class NormalCognitionLabCase:
    """登録済みの正規入力。自然言語から製品の意味を補作しない。"""

    fixture: ValidationFixture
    admission: InputAdmission

    def typed_inputs(self) -> JsonValue:
        return _project(self.admission)


NormalCognitionApplicationFactory = Callable[[], MinimumCoreApplication]


def _result_projection(result: object) -> JsonValue:
    if result is None:
        return None
    if isinstance(result, InputMeaningInterpretationResult):
        return _project(result.to_dict())
    if isinstance(result, CommittedExecutiveDecision):
        return _project(result.to_dict())
    if isinstance(result, AppraisalStateCommit):
        return _project(result)
    raise ValueError("通常認知の公開結果型ではありません")


def _status(status: BrainWorkStatus, result: object) -> RunStatus:
    if status is BrainWorkStatus.CANCELLED:
        return RunStatus.CANCELLED
    if status is BrainWorkStatus.TIMED_OUT:
        return RunStatus.TIMED_OUT
    if status is not BrainWorkStatus.COMPLETED:
        return RunStatus.PRODUCT_FAILED
    if isinstance(result, InputMeaningInterpretationResult):
        return input_meaning_run_status(result)
    return RunStatus.COMPLETED


@dataclass
class _IterationApplication:
    """runに登録する終了処理は1件とし、現在iterationの資源だけを保持する。"""

    current: MinimumCoreApplication | None = None

    async def stop(self) -> None:
        if self.current is not None:
            await self.current.stop()
            self.current = None


def normal_cognition_target(
    cases: tuple[NormalCognitionLabCase, ...],
    application_factory: NormalCognitionApplicationFactory,
    provenance: ProductionTargetProvenance,
    contract_revision: str,
    provider_policy_refs: tuple[str, ...],
) -> LabTarget:
    """trusted起動側が供給するfresh applicationをiteration単位で所有する。"""
    registered = {case.fixture.scenario_id: case for case in cases}
    if len(registered) != len(cases) or not callable(application_factory):
        raise ValueError("通常認知の検証条件または起動factoryが不正です")

    ownership: WeakKeyDictionary[RunContext, _IterationApplication] = WeakKeyDictionary()

    async def run(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        case = registered.get(fixture.scenario_id)
        if (
            case is None
            or case.fixture != fixture
            or case.typed_inputs() != fixture.typed_inputs
            or case.admission.status is not InputAdmissionStatus.ACCEPTED
            or case.admission.event is None
        ):
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        owner = ownership.get(context)
        if owner is None:
            owner = _IterationApplication()
            context.add_cleanup("cognition.stop", owner.stop)
            ownership[context] = owner
        if owner.current is not None:
            raise ValueError("前iterationのアプリケーションが未停止です")
        app = application_factory()
        if not isinstance(app, MinimumCoreApplication):
            raise ValueError("factoryは正規MinimumCoreApplicationを返す必要があります")
        owner.current = app
        stop = owner.stop
        if app.cognition is None:
            await stop()
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        await context.invoke_product("cognition.start", app.start)

        async def submit() -> object:
            assert app.cognition is not None
            return app.cognition.submit_input(case.admission)

        from app.domain.brain_integration import BrainWorkAdmission

        accepted = await context.invoke_product("cognition.submit_input", submit)
        assert isinstance(accepted, BrainWorkAdmission)
        if not accepted.accepted:
            await stop()
            return TargetObservation(
                RunStatus.PRODUCT_FAILED, Gate.FAIL, _project({"admission": accepted})
            )
        event = case.admission.event.envelope
        observed: set[str] = set()
        outputs: list[JsonValue] = []
        status = RunStatus.PRODUCT_FAILED
        complete = False
        # module別の段数表は持たず、実際のtraceの未観測workを追う。
        # 有限な通常認知module集合とLabPolicyの双方で観測数を制限する。
        for _ in range(min(len(BrainIntegrationModule), context.policy.max_intervals)):
            outcome = await context.invoke_product("cognition.outcome", app.brain.next_outcome)
            trace = app.brain.trace(event.trace_id)
            if (
                outcome.trace_id != event.trace_id
                or outcome.work_id in observed
                or outcome.work_id not in {i.work_id for i in trace.intervals}
            ):
                raise ValueError("通常認知の公開outcomeとtraceが一致しません")
            observed.add(outcome.work_id)
            outputs.append(
                _project(
                    {
                        "work_id": outcome.work_id,
                        "trace_id": outcome.trace_id,
                        "module": outcome.module,
                        "lane": outcome.lane,
                        "status": outcome.status,
                        "completed_at": outcome.completed_at,
                        "result": _result_projection(outcome.result),
                    }
                )
            )
            status = _status(outcome.status, outcome.result)
            if status is not RunStatus.COMPLETED:
                break
            if outcome.module is BrainIntegrationModule.EXECUTIVE:
                complete = isinstance(outcome.result, CommittedExecutiveDecision)
                break
            if not any(i.work_id not in observed for i in trace.intervals):
                # 配送先がない正常な型付き非成功を、後段成功へ読み替えない。
                status = RunStatus.PRODUCT_FAILED
                break
        trace = app.brain.trace(event.trace_id)
        structural = (
            complete
            and status is RunStatus.COMPLETED
            and trace.root_trigger_id == event.event_id
            and trace.source_event_ids == (event.event_id,)
            and observed == {i.work_id for i in trace.intervals}
            and all(i.status is BrainWorkStatus.COMPLETED for i in trace.intervals)
        )
        if status is RunStatus.COMPLETED and not structural:
            status = RunStatus.PRODUCT_FAILED
        await context.invoke_product("cognition.stop", stop)
        return TargetObservation(
            status,
            Gate.PASS if structural else Gate.FAIL,
            _project(
                {
                    "admission": accepted,
                    "outcomes": outputs,
                    "trace": trace,
                }
            ),
        )

    return LabTarget(
        "normal_cognition",
        contract_revision,
        frozenset({LabMode.INTEGRATED}),
        provider_policy_refs,
        provenance,
        run,
    )
