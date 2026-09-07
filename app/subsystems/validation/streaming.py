"""配信の既存実行入口を呼び、効果の報告をそのまま記録する。"""

import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from enum import Enum
from typing import cast

from app.domain.contracts.common import JsonValue, freeze_json
from app.subsystems.streaming.contracts import (
    StreamingCapabilityView,
    StreamingCommentEvent,
    StreamingCommentModerationState,
    StreamingExecutionReport,
    StreamingExecutionRequest,
    StreamingExecutionStatus,
)
from app.subsystems.streaming.runtime import (
    StreamingCommentModerationPort,
    StreamingProviderPort,
    StreamingSubsystemRuntime,
)

from .contracts import (
    Gate,
    LabMode,
    ProductionTargetProvenance,
    RunStatus,
    TargetObservation,
    ValidationFixture,
    aware,
)
from .runtime import LabTarget, RunContext
from .streaming_monitor import StreamingMonitorSettings, observe_streaming


def _encode(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise ValueError("配信の公開契約に未対応の値があります")


def _project(value: object) -> JsonValue:
    return freeze_json(
        cast(JsonValue, json.loads(json.dumps(value, default=_encode, allow_nan=False)))
    )


@dataclass(frozen=True)
class StreamingLabCase:
    fixture: ValidationFixture
    capability: StreamingCapabilityView
    requests: tuple[StreamingExecutionRequest, ...]
    observed_at: datetime
    monitor: StreamingMonitorSettings | None = None

    def __post_init__(self) -> None:
        aware(self.observed_at)
        if not isinstance(self.capability, StreamingCapabilityView):
            raise ValueError("配信の能力情報が不正です")
        if (not self.requests and self.monitor is None) or any(
            not isinstance(x, StreamingExecutionRequest) for x in self.requests
        ):
            raise ValueError("配信の型付き実行要求が必要です")
        if self.monitor is not None and not isinstance(self.monitor, StreamingMonitorSettings):
            raise ValueError("配信監視の設定が不正です")
        object.__setattr__(self, "requests", tuple(self.requests))

    def typed_inputs(self) -> JsonValue:
        return _project(
            {
                "capability": asdict(self.capability),
                "requests": [asdict(x) for x in self.requests],
                "observed_at": self.observed_at,
                "monitor": asdict(self.monitor) if self.monitor is not None else None,
            }
        )


def streaming_target(
    cases: tuple[StreamingLabCase, ...],
    provider: StreamingProviderPort,
    provenance: ProductionTargetProvenance,
    contract_revision: str,
    *,
    moderator: StreamingCommentModerationPort | None = None,
) -> LabTarget:
    registered = {case.fixture.scenario_id: case for case in cases}
    if len(registered) != len(cases):
        raise ValueError("配信の検証条件は重複できません")

    async def run(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        case = registered.get(fixture.scenario_id)
        if case is None or case.fixture != fixture or case.typed_inputs() != fixture.typed_inputs:
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)

        class ObservedProvider:
            async def execute(self, request: StreamingExecutionRequest) -> StreamingExecutionReport:
                return await context.invoke_port(
                    "streaming.provider", lambda: provider.execute(request)
                )

        class ObservedModerator:
            async def moderate(
                self, comment: StreamingCommentEvent
            ) -> StreamingCommentModerationState:
                assert moderator is not None
                return await context.invoke_port(
                    "streaming.moderation", lambda: moderator.moderate(comment)
                )

        owner = StreamingSubsystemRuntime(
            ObservedProvider(),
            case.capability,
            clock=lambda: case.observed_at,
            moderator=ObservedModerator() if moderator is not None else None,
            comment_limit=case.monitor.comment_limit if case.monitor is not None else 64,
        )
        context.add_cleanup("streaming.runtime", owner.shutdown)

        async def monitor() -> object:
            assert case.monitor is not None
            return await observe_streaming(context, owner, case.monitor)

        monitor_task = (
            context.spawn("streaming.monitor", monitor) if case.monitor is not None else None
        )
        reports: list[dict[str, object]] = []
        status = RunStatus.COMPLETED
        for index, original in enumerate(case.requests):
            prefix = f"{context.run_id}:{fixture.scenario_id}:{context.iteration}:{index}"
            request = replace(original, execution_id=prefix, trace_id=prefix)

            async def execute(
                item: StreamingExecutionRequest = request,
            ) -> StreamingExecutionReport:
                return await owner.execute(item)

            report = await context.invoke_product("streaming.execute", execute)
            reports.append(asdict(report))
            if report.status is not StreamingExecutionStatus.SUCCEEDED:
                status = {
                    StreamingExecutionStatus.TIMED_OUT: RunStatus.TIMED_OUT,
                    StreamingExecutionStatus.CANCELLED: RunStatus.CANCELLED,
                    StreamingExecutionStatus.PROVIDER_UNAVAILABLE: RunStatus.PROVIDER_FAILED,
                }.get(report.status, RunStatus.PRODUCT_FAILED)
                break
        monitoring = await monitor_task if monitor_task is not None else None
        lifecycle = owner.lifecycle
        # 観測期間に残った審査処理も回収し、期間内の未完了数とは分けて記録する。
        await owner.shutdown()
        return TargetObservation(
            status,
            Gate.NOT_RUN,
            _project(
                {
                    "reports": reports,
                    "lifecycle": lifecycle,
                    "lifecycle_after_shutdown": owner.lifecycle,
                    "monitor": monitoring,
                    "pending_streaming_tasks": owner.pending_task_count,
                }
            ),
        )

    return LabTarget(
        "streaming",
        contract_revision,
        frozenset({LabMode.ISOLATION}),
        (),
        provenance,
        run,
        frozenset({"streaming.provider", "streaming.moderation"}),
    )
