"""本番の活動受付・配信操作・効果確定を接続して検証する。"""

import asyncio
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from app.domain.activity_execution import (
    ActivityExecutionAuthority,
    ActivityExecutionCoordinator,
    ActivityInterruptibility,
    ActivityInvocation,
    ExecutionDispatchRequest,
    ExecutionPreflightSnapshot,
)
from app.domain.activity_execution.contracts import ExecutionEffectUncertainty
from app.domain.contracts import (
    CapabilityAvailability,
    CapabilityDescriptor,
    CapabilityRequirement,
    ExecutionStatus,
)
from app.subsystems.streaming.activity import (
    StreamingActivityExecutionAdapter,
    StreamingActivityOperationBinding,
)
from app.subsystems.streaming.contracts import (
    StreamingCapabilityView,
    StreamingEffectState,
    StreamingExecutionReport,
    StreamingExecutionRequest,
    StreamingExecutionStatus,
    StreamingOperation,
)
from app.subsystems.streaming.runtime import StreamingSubsystemRuntime
from tests.domain.activity_execution import test_activity_execution as activity

NOW = activity.NOW


class Provider:
    def __init__(
        self,
        *,
        status: StreamingExecutionStatus = StreamingExecutionStatus.SUCCEEDED,
        effect: StreamingEffectState = StreamingEffectState.APPLIED,
        blocked: bool = False,
        completed_at: datetime = NOW,
    ) -> None:
        self.status, self.effect, self.completed_at = status, effect, completed_at
        self.calls: list[StreamingExecutionRequest] = []
        self.entered, self.release, self.cancelled = (
            asyncio.Event(),
            asyncio.Event(),
            asyncio.Event(),
        )
        if not blocked:
            self.release.set()

    async def execute(self, request: StreamingExecutionRequest) -> StreamingExecutionReport:
        self.calls.append(request)
        self.entered.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        return StreamingExecutionReport(
            request.execution_id,
            request.operation,
            self.status,
            self.effect,
            self.completed_at,
            ("observation:external",),
            False,
            ("PUBLIC_DIAGNOSTIC",),
        )


class Clock:
    def now(self) -> datetime:
        return NOW


class Preflight:
    def __init__(self, *, drift: bool = False) -> None:
        self.calls = 0
        self.drift = drift

    async def current_for(self, item: ActivityInvocation) -> ExecutionPreflightSnapshot:
        self.calls += 1
        descriptor = CapabilityDescriptor(
            "stream-cap",
            "streaming",
            tuple(op.value for op in StreamingOperation),
            CapabilityAvailability.AVAILABLE,
            3 if self.drift and self.calls > 1 else 2,
            {},
        )
        return activity.preflight(capabilities=(descriptor,), preconditions=())


def invocation(
    operation: StreamingOperation = StreamingOperation.START_STREAM,
) -> ActivityInvocation:
    command = replace(
        activity.command(),
        preconditions=(),
        required_capabilities=(CapabilityRequirement("streaming", operation.value),),
    )
    return replace(
        activity.invocation(),
        command=command,
        operation_ref=f"stream.{operation.value}",
        arguments={},
    )


def adapter(
    provider: Provider,
) -> tuple[StreamingActivityExecutionAdapter, StreamingSubsystemRuntime]:
    runtime = StreamingSubsystemRuntime(
        provider,
        StreamingCapabilityView("stream-cap", 2, tuple(StreamingOperation), True, 1),
        clock=lambda: NOW,
    )
    port = StreamingActivityExecutionAdapter(
        runtime,
        tuple(
            StreamingActivityOperationBinding("stream-cap", f"stream.{op.value}", op)
            for op in StreamingOperation
        ),
        lambda: NOW,
    )
    return port, runtime


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", tuple(StreamingOperation))
async def test_selected_operation_reaches_streaming_and_effect_authority(
    operation: StreamingOperation,
) -> None:
    provider, preflight, authority = Provider(), Preflight(), ActivityExecutionAuthority()
    port, runtime = adapter(provider)
    item = invocation(operation)
    coordinator = ActivityExecutionCoordinator(preflight, port, authority, Clock())
    record = await coordinator.execute(item)
    assert preflight.calls == 2 and len(provider.calls) == 1
    request = provider.calls[0]
    assert request.execution_id == record.dispatch_id
    assert request.activity_id == item.command.command_id
    assert request.operation is operation
    assert request.descriptor_revision == 2
    assert request.source_context_revision == item.command.revisions.source_context_revision
    assert request.goal_revision == item.command.revisions.goal_revision
    assert request.attention_revision == item.command.revisions.attention_revision
    assert record.result.status is ExecutionStatus.COMPLETED
    assert record.result.effect_refs == (f"{record.dispatch_id}:streaming-effect",)
    assert isinstance(record.result.details, Mapping)
    assert record.result.details["streaming_status"] == "succeeded"
    assert "state" not in record.result.details
    assert authority.snapshot(item.command.command_id) == record
    await runtime.shutdown()
    assert runtime.pending_task_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,effect,expected,uncertainty",
    [
        (
            StreamingExecutionStatus.FAILED,
            StreamingEffectState.NOT_APPLIED,
            ExecutionStatus.FAILED,
            ExecutionEffectUncertainty.NONE,
        ),
        (
            StreamingExecutionStatus.FAILED,
            StreamingEffectState.AMBIGUOUS,
            ExecutionStatus.FAILED,
            ExecutionEffectUncertainty.POSSIBLY_APPLIED,
        ),
        (
            StreamingExecutionStatus.PROVIDER_UNAVAILABLE,
            StreamingEffectState.UNKNOWN,
            ExecutionStatus.FAILED,
            ExecutionEffectUncertainty.UNKNOWN,
        ),
        (
            StreamingExecutionStatus.UNKNOWN_EFFECT,
            StreamingEffectState.AMBIGUOUS,
            ExecutionStatus.FAILED,
            ExecutionEffectUncertainty.POSSIBLY_APPLIED,
        ),
        (
            StreamingExecutionStatus.CANCELLED,
            StreamingEffectState.UNKNOWN,
            ExecutionStatus.CANCELLED,
            ExecutionEffectUncertainty.UNKNOWN,
        ),
        (
            StreamingExecutionStatus.TIMED_OUT,
            StreamingEffectState.AMBIGUOUS,
            ExecutionStatus.TIMED_OUT,
            ExecutionEffectUncertainty.POSSIBLY_APPLIED,
        ),
    ],
)
async def test_failure_effect_uncertainty_survives_activity_commit(
    status: StreamingExecutionStatus,
    effect: StreamingEffectState,
    expected: ExecutionStatus,
    uncertainty: ExecutionEffectUncertainty,
) -> None:
    port, runtime = adapter(Provider(status=status, effect=effect))
    record = await ActivityExecutionCoordinator(
        Preflight(), port, ActivityExecutionAuthority(), Clock()
    ).execute(invocation())
    assert record.result.status is expected and record.effect_uncertainty is uncertainty
    assert record.result.effect_refs == ()
    assert isinstance(record.result.details, Mapping)
    assert record.result.details["diagnostics"] == ("PUBLIC_DIAGNOSTIC",)
    await runtime.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["arguments", "operation", "preflight"])
async def test_invalid_request_never_calls_streaming_provider(invalid: str) -> None:
    provider = Provider()
    port, runtime = adapter(provider)
    item = invocation()
    if invalid == "arguments":
        item = replace(item, arguments={"unregistered": "value"})
    if invalid == "operation":
        item = replace(item, operation_ref="not-bound")
    record = await ActivityExecutionCoordinator(
        Preflight(drift=invalid == "preflight"), port, ActivityExecutionAuthority(), Clock()
    ).execute(item)
    assert record.result.status is (
        ExecutionStatus.SUPERSEDED if invalid == "preflight" else ExecutionStatus.FAILED
    )
    assert record.effect_uncertainty is ExecutionEffectUncertainty.NONE
    assert provider.calls == []
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_cancel_before_dispatch_calls_no_provider() -> None:
    provider = Provider()
    port, runtime = adapter(provider)
    item, owner = invocation(), ActivityExecutionAuthority()
    accepted = owner.admit(item, await Preflight().current_for(item)).record
    request = ExecutionDispatchRequest("dispatch", item, accepted.result, accepted.bindings)

    class Cancelled:
        cancelled = True
        hard_interrupt_allowed = True

    reports = await port.execute(request, Cancelled())
    assert reports[0].status is ExecutionStatus.CANCELLED
    assert reports[0].effect_uncertainty is ExecutionEffectUncertainty.NONE
    assert provider.calls == []
    await runtime.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("interruptible", [False, True])
async def test_cancellation_respects_activity_interruptibility(interruptible: bool) -> None:
    provider = Provider(blocked=True)
    port, runtime = adapter(provider)
    item = replace(
        invocation(),
        interruptibility=(
            ActivityInterruptibility.INTERRUPTIBLE
            if interruptible
            else ActivityInterruptibility.SOFT_CANCEL_ONLY
        ),
    )
    coordinator = ActivityExecutionCoordinator(
        Preflight(), port, ActivityExecutionAuthority(), Clock()
    )
    task = asyncio.create_task(coordinator.execute(item))
    await asyncio.wait_for(provider.entered.wait(), 0.5)
    await coordinator.cancel(item.command.command_id, "利用者の取消要求")
    if not interruptible:
        assert not task.done() and not provider.cancelled.is_set()
        provider.release.set()
    record = await task
    assert record.result.status is (
        ExecutionStatus.CANCELLED if interruptible else ExecutionStatus.COMPLETED
    )
    assert record.cancellation_reason == "利用者の取消要求"
    assert record.effect_uncertainty is (
        ExecutionEffectUncertainty.POSSIBLY_APPLIED
        if interruptible
        else ExecutionEffectUncertainty.NONE
    )
    assert bool(record.result.effect_refs) is not interruptible
    await runtime.shutdown()
    assert runtime.pending_task_count == 0


@pytest.mark.asyncio
async def test_late_applied_effect_is_preserved_when_activity_deadline_expires() -> None:
    provider = Provider(completed_at=NOW + timedelta(seconds=2))
    port, runtime = adapter(provider)
    item = invocation()
    item = replace(item, command=replace(item.command, deadline_at=NOW + timedelta(seconds=1)))
    record = await ActivityExecutionCoordinator(
        Preflight(), port, ActivityExecutionAuthority(), Clock()
    ).execute(item)
    assert record.result.status is ExecutionStatus.TIMED_OUT
    assert len(record.result.effect_refs) == 1
    assert provider.calls[0].deadline_at == item.command.deadline_at
    await runtime.shutdown()
