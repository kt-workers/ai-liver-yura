"""本番の実行基盤を通し、受付待機と提供サービス呼出しを別に計測する。"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from enum import Enum
from time import monotonic_ns
from typing import cast

from app.domain.contracts.common import JsonValue, freeze_json
from app.domain.llm import LLMRoleRequest, LLMRoleResult
from app.runtime.kernel import (
    QueuePolicy,
    RuntimeCoordinator,
    RuntimeLanePolicy,
    RuntimeSchedulerPolicy,
    RuntimeWorkItem,
)
from app.runtime.kernel.cancellation import CancellationToken
from app.runtime.kernel.clock import SystemRuntimeClock
from app.runtime.shutdown import RuntimeShutdownPolicy
from app.usecases.ports.llm import LLMRolePort

from .contracts import (
    Gate,
    LabMode,
    ProductionTargetProvenance,
    RunStatus,
    TargetObservation,
    ValidationFixture,
)
from .runtime import LabTarget, RunContext


def _encode(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return dict(value)
    if (
        is_dataclass(value)
        and not isinstance(value, type)
        and type(value).__module__.startswith(
            ("app.runtime.", "app.domain.llm.", "app.domain.contracts.")
        )
    ):
        return {field.name: getattr(value, field.name) for field in fields(value)}
    raise ValueError("実行基盤の公開契約に未対応の値があります")


def _project(value: object) -> JsonValue:
    return freeze_json(
        cast(JsonValue, json.loads(json.dumps(value, default=_encode, allow_nan=False)))
    )


@dataclass(frozen=True)
class ProviderSchedulingCase:
    fixture: ValidationFixture
    work: tuple[RuntimeWorkItem[LLMRoleRequest], ...]
    lanes: tuple[RuntimeLanePolicy, ...]
    scheduler: RuntimeSchedulerPolicy
    shutdown: RuntimeShutdownPolicy

    def __post_init__(self) -> None:
        if not self.work or len({x.work_id for x in self.work}) != len(self.work):
            raise ValueError("実行要求の識別子は一意でなければなりません")
        if any(not isinstance(x.payload, LLMRoleRequest) for x in self.work):
            raise ValueError("既存のLLM要求が必要です")
        if len({x.lane_id for x in self.lanes}) != len(self.lanes):
            raise ValueError("処理列の識別子は一意でなければなりません")
        if not {x.lane_id for x in self.work} <= {x.lane_id for x in self.lanes}:
            raise ValueError("実行要求の処理列が未登録です")
        object.__setattr__(self, "work", tuple(self.work))
        object.__setattr__(self, "lanes", tuple(self.lanes))

    def typed_inputs(self) -> JsonValue:
        return _project(
            {
                "work": self.work,
                "lanes": self.lanes,
                "scheduler": self.scheduler,
                "shutdown": self.shutdown,
            }
        )


def provider_scheduling_target(
    cases: tuple[ProviderSchedulingCase, ...],
    port: LLMRolePort,
    provenance: ProductionTargetProvenance,
    contract_revision: str,
) -> LabTarget:
    registered = {case.fixture.scenario_id: case for case in cases}
    if len(registered) != len(cases):
        raise ValueError("順序制御の検証条件は重複できません")

    async def run(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        case = registered.get(fixture.scenario_id)
        if case is None or case.fixture != fixture or case.typed_inputs() != fixture.typed_inputs:
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        if (
            len(case.work) > context.policy.max_intervals
            or len(case.lanes) > context.policy.max_tasks
            or any(lane.queue_policy is QueuePolicy.COALESCE for lane in case.lanes)
        ):
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        owner = RuntimeCoordinator(SystemRuntimeClock(), case.scheduler, case.shutdown)
        context.add_cleanup("provider.scheduler", owner.stop)
        submitted: dict[str, int] = {}
        measurements: list[dict[str, object]] = []

        async def handle(
            work: RuntimeWorkItem[LLMRoleRequest], token: CancellationToken
        ) -> LLMRoleResult:
            started = monotonic_ns()
            result: LLMRoleResult | None = None
            try:
                result = await context.invoke_port(
                    "provider.invoke", lambda: port.invoke(work.payload)
                )
                return result
            finally:
                measurements.append(
                    {
                        "work_id": work.work_id,
                        "lane_id": work.lane_id,
                        "admission_to_handler_ns": started - submitted[work.work_id],
                        "provider_call_ns": monotonic_ns() - started,
                        "role_status": result.status.value if result is not None else None,
                        "attempt_count": result.attempt_count if result is not None else None,
                        "token_usage": result.token_usage.to_dict() if result is not None else None,
                    }
                )

        for lane in case.lanes:
            owner.register_lane(lane, handle)
        await owner.start()
        pending: set[str] = set()
        admissions: list[dict[str, object]] = []
        for work in case.work:
            submitted[work.work_id] = monotonic_ns()
            admission = owner.submit(work)
            admissions.append({"work_id": work.work_id, "admission": admission})
            pending.difference_update(admission.displaced_work_ids)
            if admission.accepted:
                pending.add(work.work_id)
        outcomes: list[dict[str, object]] = []
        while pending:
            outcome = await owner.next_outcome()
            pending.discard(outcome.work_id)
            # 実行基盤が保持する生の例外説明は投影しない。
            outcomes.append({"work_id": outcome.work_id, "disposition": outcome.disposition})
        return TargetObservation(
            RunStatus.COMPLETED,
            Gate.NOT_RUN,
            _project(
                {
                    "admissions": admissions,
                    "measurements": measurements,
                    "outcomes": outcomes,
                }
            ),
        )

    return LabTarget(
        "provider_scheduling",
        contract_revision,
        frozenset({LabMode.ISOLATION}),
        (),
        provenance,
        run,
        frozenset({"provider.invoke"}),
    )
