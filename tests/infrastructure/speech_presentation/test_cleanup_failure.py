"""cleanupの各待機失敗を決定的に注入する。"""

import asyncio
from typing import Any
from unittest.mock import Mock

import pytest

from app.domain.speech_runtime.execution import PresentationExecutionError
from app.domain.speech_runtime.execution import PresentationExecutionFailureCode as Code
from tests.domain.speech_runtime.test_presentation_timeout import committed
from tests.infrastructure.speech_presentation.test_process import boundary, policy


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["stdin", "drain", "process", "stdin_error", "drain_error"])
async def test_cleanup_timeout_is_typed_and_drain_reaped(phase: str) -> None:
    pending: set[asyncio.Task[Any]] = set()

    async def blocked() -> None:
        task = asyncio.current_task()
        assert task is not None
        pending.add(task)
        try:
            await asyncio.Event().wait()
        finally:
            pending.discard(task)

    class Stdin:
        def close(self) -> None:
            pass

        async def wait_closed(self) -> None:
            if phase == "stdin":
                await blocked()
            if phase == "stdin_error":
                raise OSError("stdin閉鎖失敗の注入")

    class Stdout:
        async def read(self, count: int) -> bytes:
            if phase == "drain_error":
                raise OSError("drain失敗の注入")
            await blocked()
            return b""

    class Process:
        stdin = Stdin()
        stdout = Stdout()
        returncode = 0

        async def wait(self) -> int:
            if phase == "process":
                await blocked()
            return 0

    _, _, command, _ = await committed()
    supervisor = boundary("normal")
    session = supervisor.open(command, policy())
    process: Any = Process()
    session._process = process
    containment = Mock()
    containment.active.return_value = False
    session._containment = containment
    try:
        with pytest.raises(PresentationExecutionError) as error:
            await session.close()
        assert error.value.code is Code.CLEANUP_FAILED
        assert session.diagnostics.failure is Code.CLEANUP_FAILED
        assert not session.diagnostics.closed
        assert supervisor.active_execution_count == 1
        assert not pending
    finally:
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
