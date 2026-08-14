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
        self._signal_lock = asyncio.Lock()

    async def execute(self, invocation: ActivityInvocation) -> ActivityExecutionRecord:
        initial = await self._preflight.current_for(invocation)
        record = self._authority.admit(invocation, initial)
        if record.terminal:
            return record
        current = await self._preflight.current_for(invocation)
        accepted_result = record.result
        record = self._authority.start(invocation.command.command_id, current, self._clock.now())
        if record.terminal:
            return record
        signal = _CancellationSignal(
            invocation.interruptibility is ActivityInterruptibility.INTERRUPTIBLE
        )
        async with self._signal_lock:
            self._signals[invocation.command.command_id] = signal
        request = ExecutionDispatchRequest(invocation, accepted_result, record.bindings)
        try:
            try:
                adapter_task = asyncio.create_task(self._port.execute(request, signal))
                if invocation.interruptibility is ActivityInterruptibility.INTERRUPTIBLE:
                    reports = tuple(await adapter_task)
                else:
                    reports = tuple(await asyncio.shield(adapter_task))
            except asyncio.CancelledError:
                if invocation.interruptibility is ActivityInterruptibility.INTERRUPTIBLE:
                    return self._authority.apply_report(
                        ExecutionAdapterReport(
                            invocation.command.command_id,
                            invocation.invocation_id,
                            ExecutionStatus.CANCELLED,
                            self._clock.now(),
                            {"code": "adapter_cancelled"},
                        )
                    )
                reports = tuple(await asyncio.shield(adapter_task))
            except Exception:
                return self._authority.apply_report(
                    ExecutionAdapterReport(
                        invocation.command.command_id,
                        invocation.invocation_id,
                        ExecutionStatus.FAILED,
                        self._clock.now(),
                        {"code": "adapter_failure"},
                    )
                )
            if not reports:
                raise ValueError("adapter must return at least one report")
            for report in reports:
                record = self._authority.apply_report(report)
            return record
        finally:
            async with self._signal_lock:
                self._signals.pop(invocation.command.command_id, None)

    async def cancel(self, command_id: str, reason: str) -> ActivityExecutionRecord:
        record = self._authority.request_cancellation(command_id, reason, self._clock.now())
        async with self._signal_lock:
            signal = self._signals.get(command_id)
            if signal is not None:
                signal.cancelled = True
        return record
