from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.domain.contracts import ExecutionStatus

from .authority import ActivityExecutionAuthority
from .contracts import (
    ActivityExecutionRecord,
    ActivityInterruptibility,
    ActivityInvocation,
    ExecutionAdapterReport,
    ExecutionDispatchRequest,
    ExecutionPreflightSnapshot,
)


class ExecutionPreflightPort(Protocol):
    async def current_for(self, invocation: ActivityInvocation) -> ExecutionPreflightSnapshot: ...


class ExecutionCancellationSignal(Protocol):
    @property
    def cancelled(self) -> bool: ...

    @property
    def hard_interrupt_allowed(self) -> bool: ...


class ActivityExecutionPort(Protocol):
    async def execute(
        self, request: ExecutionDispatchRequest, cancellation: ExecutionCancellationSignal
    ) -> Sequence[ExecutionAdapterReport]: ...


class ExecutionClock(Protocol):
    def now(self) -> datetime: ...


@dataclass(slots=True)
class _CancellationSignal:
    hard_interrupt_allowed: bool
    cancelled: bool = False


class ActivityExecutionCoordinator:
    def __init__(
        self,
        preflight: ExecutionPreflightPort,
        port: ActivityExecutionPort,
        authority: ActivityExecutionAuthority,
        clock: ExecutionClock,
    ) -> None:
        self._preflight = preflight
        self._port = port
        self._authority = authority
        self._clock = clock
        self._signals: dict[str, _CancellationSignal] = {}
        self._adapter_tasks: dict[
            str, asyncio.Task[Sequence[ExecutionAdapterReport]]
        ] = {}
        self._signal_lock = asyncio.Lock()

    async def execute(self, invocation: ActivityInvocation) -> ActivityExecutionRecord:
        initial = await self._preflight.current_for(invocation)
        record = self._authority.admit(invocation, initial)
        if record.terminal:
            return record
        command_id = invocation.command.command_id
        dispatch_id = f"{command_id}:{invocation.invocation_id}"
        signal = _CancellationSignal(
            invocation.interruptibility is ActivityInterruptibility.INTERRUPTIBLE
        )
        async with self._signal_lock:
            self._signals[command_id] = signal
        adapter_task: asyncio.Task[Sequence[ExecutionAdapterReport]] | None = None
        try:
            current = await self._preflight.current_for(invocation)
            accepted_result = record.result
            record = self._authority.start(
                command_id, current, self._clock.now(), dispatch_id
            )
            if record.terminal:
                return record
            request = ExecutionDispatchRequest(
                dispatch_id, invocation, accepted_result, record.bindings
            )
            try:
                adapter_task = asyncio.create_task(self._port.execute(request, signal))
                async with self._signal_lock:
                    self._adapter_tasks[command_id] = adapter_task
                    cancel_immediately = signal.cancelled and signal.hard_interrupt_allowed
                if cancel_immediately:
                    adapter_task.cancel()
                if invocation.interruptibility is ActivityInterruptibility.INTERRUPTIBLE:
                    reports = tuple(await adapter_task)
                else:
                    reports = tuple(await asyncio.shield(adapter_task))
            except asyncio.CancelledError:
                if invocation.interruptibility is ActivityInterruptibility.INTERRUPTIBLE:
                    self._authority.request_cancellation(
                        command_id, "execution_task_cancelled", self._clock.now()
                    )
                    return self._authority.apply_report(
                        ExecutionAdapterReport(
                            command_id=command_id,
                            invocation_id=invocation.invocation_id,
                            dispatch_id=dispatch_id,
                            status=ExecutionStatus.CANCELLED,
                            occurred_at=self._clock.now(),
                            details={"code": "adapter_cancelled"},
                        )
                    )
                self._authority.request_cancellation(
                    command_id, "execution_task_cancelled", self._clock.now()
                )
                assert adapter_task is not None
                reports = tuple(await asyncio.shield(adapter_task))
            except Exception:
                return self._authority.apply_report(
                    ExecutionAdapterReport(
                        command_id=command_id,
                        invocation_id=invocation.invocation_id,
                        dispatch_id=dispatch_id,
                        status=ExecutionStatus.FAILED,
                        occurred_at=self._clock.now(),
                        details={"code": "adapter_failure"},
                    )
                )
            if not reports:
                return self._authority.fail_adapter_contract(command_id, self._clock.now())
            try:
                for report in reports:
                    if not isinstance(report, ExecutionAdapterReport):
                        raise ValueError("adapter returned an invalid report")
                    record = self._authority.apply_report(report)
            except (TypeError, ValueError):
                return self._authority.fail_adapter_contract(command_id, self._clock.now())
            return record
        except asyncio.CancelledError:
            record = self._authority.request_cancellation(
                command_id, "execution_task_cancelled", self._clock.now()
            )
            signal.cancelled = True
            if record.terminal:
                return record
            if adapter_task is not None and signal.hard_interrupt_allowed:
                adapter_task.cancel()
            if record.dispatch_id is None:
                return self._authority.snapshot(command_id) or record
            return self._authority.apply_report(
                ExecutionAdapterReport(
                    command_id=command_id,
                    invocation_id=invocation.invocation_id,
                    dispatch_id=record.dispatch_id,
                    status=ExecutionStatus.CANCELLED,
                    occurred_at=self._clock.now(),
                    details={"code": "execution_task_cancelled"},
                )
            )
        finally:
            async with self._signal_lock:
                self._signals.pop(command_id, None)
                current_task = self._adapter_tasks.get(command_id)
                if current_task is adapter_task:
                    self._adapter_tasks.pop(command_id, None)

    async def cancel(self, command_id: str, reason: str) -> ActivityExecutionRecord:
        record = self._authority.request_cancellation(command_id, reason, self._clock.now())
        async with self._signal_lock:
            signal = self._signals.get(command_id)
            if signal is not None:
                signal.cancelled = True
                adapter_task = self._adapter_tasks.get(command_id)
                if signal.hard_interrupt_allowed and adapter_task is not None:
                    adapter_task.cancel()
        return record
