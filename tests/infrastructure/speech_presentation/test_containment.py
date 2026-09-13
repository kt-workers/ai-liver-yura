"""Windows Job境界をOSの実機成功と区別して検証する。"""

import asyncio
import ctypes
import os
from typing import Any
from unittest.mock import Mock

import pytest

from app.domain.speech_runtime.execution import PresentationExecutionError
from app.domain.speech_runtime.execution import PresentationExecutionFailureCode as Code
from app.infrastructure.speech_presentation import supervisor as module
from app.infrastructure.speech_presentation.containment import (
    PosixProcessGroup,
    WindowsJob,
    WindowsJobApi,
    _Accounting,
    _ExtendedLimits,
)
from tests.domain.speech_runtime.test_presentation_timeout import committed
from tests.infrastructure.speech_presentation.test_process import boundary, policy


def native() -> tuple[WindowsJobApi, Any]:
    library = Mock()
    library.CreateJobObjectW.return_value = 101
    library.OpenProcess.return_value = 202
    for name in (
        "SetInformationJobObject",
        "AssignProcessToJobObject",
        "QueryInformationJobObject",
        "TerminateJobObject",
        "CloseHandle",
    ):
        getattr(library, name).return_value = 1
    return WindowsJobApi(library), library


def test_windows_native_job_limits_membership_accounting_and_handles() -> None:
    api, library = native()

    def limits(job: int, kind: int, data: Any, size: int) -> int:
        assert (job, kind, size) == (101, 9, ctypes.sizeof(_ExtendedLimits))
        value = ctypes.cast(data, ctypes.POINTER(_ExtendedLimits)).contents
        assert value.BasicLimitInformation.LimitFlags == 0x2000
        return 1

    def accounting(job: int, kind: int, data: Any, size: int, returned: Any) -> int:
        assert (job, kind, size) == (101, 1, ctypes.sizeof(_Accounting))
        ctypes.cast(data, ctypes.POINTER(_Accounting)).contents.ActiveProcesses = 2
        return 1

    library.SetInformationJobObject.side_effect = limits
    library.QueryInformationJobObject.side_effect = accounting
    job = WindowsJob(api)
    job.attach(303)
    library.OpenProcess.assert_called_once_with(0x101, False, 303)
    library.AssignProcessToJobObject.assert_called_once_with(101, 202)
    library.CloseHandle.assert_called_once_with(202)
    assert job.active()
    process = Mock()
    job.terminate(process, force=False)
    job.terminate(process, force=True)
    assert library.TerminateJobObject.call_count == 2
    process.kill.assert_not_called()
    job.close()
    job.close()
    library.CloseHandle.assert_called_with(101)
    assert not job.active()
    assert library.CreateJobObjectW.restype is ctypes.c_void_p
    assert library.OpenProcess.restype is ctypes.c_void_p


@pytest.mark.parametrize(
    "failure",
    [
        "CreateJobObjectW",
        "SetInformationJobObject",
        "OpenProcess",
        "AssignProcessToJobObject",
        "QueryInformationJobObject",
        "TerminateJobObject",
        "CloseHandle",
    ],
)
def test_windows_native_failures_are_not_success(failure: str) -> None:
    api, library = native()
    getattr(library, failure).return_value = 0
    with pytest.raises(OSError):
        if failure in ("CreateJobObjectW", "SetInformationJobObject"):
            api.create()
        elif failure in ("OpenProcess", "AssignProcessToJobObject"):
            api.assign(101, 303)
        elif failure == "QueryInformationJobObject":
            api.active_count(101)
        elif failure == "TerminateJobObject":
            api.terminate(101)
        else:
            api.close(101)
    if failure == "SetInformationJobObject":
        library.CloseHandle.assert_called_once_with(101)
    if failure == "AssignProcessToJobObject":
        library.CloseHandle.assert_called_once_with(202)


@pytest.mark.asyncio
@pytest.mark.parametrize("assign_failure", [False, True])
async def test_job_assignment_precedes_command(
    monkeypatch: pytest.MonkeyPatch, assign_failure: bool
) -> None:
    events: list[str] = []
    api = Mock()
    api.create.return_value = 101
    api.active_count.return_value = 0

    def assign(job: int, pid: int) -> None:
        events.append("assign")
        if assign_failure:
            raise OSError("割当失敗の注入")

    api.assign.side_effect = assign
    containment = WindowsJob(api)
    monkeypatch.setattr(module, "create_containment", lambda: containment)
    process = Mock()
    process.pid = 303
    process.returncode = 0
    process.stdin.write.side_effect = lambda data: events.append("command")
    exited = asyncio.Event()
    if not assign_failure:
        exited.set()
    process.kill.side_effect = exited.set

    async def drain() -> None:
        pass

    async def wait() -> int:
        await exited.wait()
        return 0

    async def read(count: int) -> bytes:
        return b""

    process.stdin.drain = drain
    process.stdin.wait_closed = drain
    process.wait = wait
    process.stdout.read = read

    async def spawn(*args: Any, **kwargs: Any) -> Any:
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    _, _, command, _ = await committed()
    supervisor = boundary("normal")
    session = supervisor.open(command, policy())
    if assign_failure:
        with pytest.raises(PresentationExecutionError) as error:
            await session._launch()
        assert error.value.code is Code.SPAWN_FAILED
        assert events == ["assign"]
    else:
        await session._launch()
        assert events == ["assign", "command"]
    await session.close()
    if assign_failure:
        process.kill.assert_called_once()
    assert session.diagnostics.closed
    api.close.assert_called_once_with(101)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["active", "terminate", "close", "nonempty"])
async def test_job_cleanup_failure_retains_tracking(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    api = Mock()
    api.create.return_value = 101
    api.active_count.return_value = 1 if failure in ("terminate", "nonempty") else 0
    if failure in ("active", "terminate", "close"):
        getattr(api, {"active": "active_count"}.get(failure, failure)).side_effect = OSError(
            "故障注入"
        )
    job = WindowsJob(api)
    job.attach(303)
    _, _, command, _ = await committed()
    supervisor = boundary("normal")
    session = supervisor.open(command, policy())
    session._containment = job
    process = Mock()
    process.stdin = None
    process.stdout = None
    process.returncode = 0

    async def wait() -> int:
        return 0

    process.wait = wait
    session._process = process
    with pytest.raises(PresentationExecutionError) as error:
        await session.close()
    assert error.value.code is Code.CLEANUP_FAILED
    assert session.diagnostics.failure is Code.CLEANUP_FAILED
    assert not session.diagnostics.closed
    assert supervisor.active_execution_count == 1
    if failure != "close":
        api.close.assert_not_called()


def test_posix_permission_error_is_not_absence(monkeypatch: pytest.MonkeyPatch) -> None:
    group = PosixProcessGroup()
    group.attach(303)
    probe = Mock(side_effect=[PermissionError(), ProcessLookupError()])
    monkeypatch.setattr(os, "killpg", probe, raising=False)
    assert group.active()
    assert not group.active()
