"""受付済みの活動要求を配信へ渡し、効果の証拠を活動の確定主体へ返す。"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from app.domain.activity_execution import (
    ExecutionAdapterReport,
    ExecutionCancellationSignal,
    ExecutionDispatchRequest,
    ExecutionEffectEvidence,
    ExecutionEffectKind,
)
from app.domain.activity_execution.contracts import ExecutionEffectUncertainty
from app.domain.contracts import ExecutionStatus
from app.domain.contracts.common import JsonValue, require_identifier

from .contracts import (
    StreamingEffectState,
    StreamingExecutionReport,
    StreamingExecutionRequest,
    StreamingExecutionStatus,
    StreamingOperation,
)
from .runtime import StreamingSubsystemRuntime


@dataclass(frozen=True, slots=True)
class StreamingActivityOperationBinding:
    capability_id: str
    operation_ref: str
    operation: StreamingOperation

    def __post_init__(self) -> None:
        require_identifier(self.capability_id, "capability_id")
        require_identifier(self.operation_ref, "operation_ref")
        if not isinstance(self.operation, StreamingOperation):
            raise ValueError("配信操作の対応先には型付き操作が必要です")


class StreamingActivityExecutionAdapter:
    """配信操作の選択と実行事実の確定は、それぞれ本体の所有者へ委ねる。"""

    def __init__(
        self,
        runtime: StreamingSubsystemRuntime,
        bindings: tuple[StreamingActivityOperationBinding, ...],
        clock: Callable[[], datetime],
    ) -> None:
        bindings = tuple(bindings)
        if not bindings or any(
            not isinstance(item, StreamingActivityOperationBinding) for item in bindings
        ):
            raise ValueError("配信操作の明示的な対応表が必要です")
        keys = {(item.capability_id, item.operation_ref) for item in bindings}
        if len(keys) != len(bindings):
            raise ValueError("配信操作の対応は能力と操作参照ごとに一意でなければなりません")
        if not isinstance(runtime, StreamingSubsystemRuntime) or not callable(clock):
            raise ValueError("配信実行基盤と時刻取得関数が必要です")
        self._runtime = runtime
        self._bindings = bindings
        self._clock = clock

    async def execute(
        self, request: ExecutionDispatchRequest, cancellation: ExecutionCancellationSignal
    ) -> tuple[ExecutionAdapterReport, ...]:
        invocation = request.invocation
        command = invocation.command
        if cancellation.cancelled:
            return (
                self._failure(request, "CANCELLED_BEFORE_STREAMING", ExecutionStatus.CANCELLED),
            )
        if invocation.arguments:
            return (self._failure(request, "UNSUPPORTED_STREAMING_ARGUMENTS"),)
        identities = {(item.capability_id, item.descriptor_revision) for item in request.bindings}
        if len(identities) != 1:
            return (self._failure(request, "STREAMING_REQUIRES_ONE_CAPABILITY"),)
        capability_id, revision = next(iter(identities))
        binding = next(
            (
                item
                for item in self._bindings
                if item.capability_id == capability_id
                and item.operation_ref == invocation.operation_ref
            ),
            None,
        )
        if binding is None:
            return (self._failure(request, "STREAMING_OPERATION_NOT_BOUND"),)
        streaming_request = StreamingExecutionRequest(
            request.dispatch_id,
            command.command_id,
            capability_id,
            revision,
            binding.operation,
            command.revisions.source_context_revision,
            request.dispatch_id,
            command.revisions.goal_revision,
            command.revisions.attention_revision,
            command.deadline_at,
        )
        report = await self._runtime.execute(streaming_request)
        if not isinstance(report, StreamingExecutionReport) or (
            report.execution_id != request.dispatch_id or report.operation is not binding.operation
        ):
            return (
                self._failure(
                    request,
                    "STREAMING_REPORT_MISMATCH",
                    uncertainty=ExecutionEffectUncertainty.UNKNOWN,
                ),
            )
        details: dict[str, JsonValue] = {
            "streaming_status": report.status.value,
            "effect_state": report.effect_state.value,
            "retryable": report.retryable,
            "diagnostics": report.sanitized_diagnostics,
        }
        if report.status is StreamingExecutionStatus.SUCCEEDED:
            evidence = ExecutionEffectEvidence(
                f"{request.dispatch_id}:streaming-effect",
                capability_id,
                revision,
                invocation.operation_ref,
                ExecutionEffectKind.APPLIED,
                {"operation": binding.operation.value, "observation_refs": report.observation_refs},
            )
            return (
                ExecutionAdapterReport(
                    command.command_id,
                    invocation.invocation_id,
                    request.dispatch_id,
                    ExecutionStatus.APPLIED,
                    report.completed_at,
                    details,
                    (evidence,),
                ),
                ExecutionAdapterReport(
                    command.command_id,
                    invocation.invocation_id,
                    request.dispatch_id,
                    ExecutionStatus.COMPLETED,
                    report.completed_at,
                    details,
                ),
            )
        status = {
            StreamingExecutionStatus.CANCELLED: ExecutionStatus.CANCELLED,
            StreamingExecutionStatus.TIMED_OUT: ExecutionStatus.TIMED_OUT,
        }.get(report.status, ExecutionStatus.FAILED)
        uncertainty = {
            StreamingEffectState.NOT_APPLIED: ExecutionEffectUncertainty.NONE,
            StreamingEffectState.AMBIGUOUS: ExecutionEffectUncertainty.POSSIBLY_APPLIED,
            StreamingEffectState.UNKNOWN: ExecutionEffectUncertainty.UNKNOWN,
        }[report.effect_state]
        return (
            ExecutionAdapterReport(
                command.command_id,
                invocation.invocation_id,
                request.dispatch_id,
                status,
                report.completed_at,
                details,
                effect_uncertainty=uncertainty,
            ),
        )

    def _failure(
        self,
        request: ExecutionDispatchRequest,
        code: str,
        status: ExecutionStatus = ExecutionStatus.FAILED,
        *,
        uncertainty: ExecutionEffectUncertainty = ExecutionEffectUncertainty.NONE,
    ) -> ExecutionAdapterReport:
        return ExecutionAdapterReport(
            request.invocation.command.command_id,
            request.invocation.invocation_id,
            request.dispatch_id,
            status,
            self._clock(),
            {"code": code},
            effect_uncertainty=uncertainty,
        )
