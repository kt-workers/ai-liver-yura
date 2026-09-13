"""DomainへOS APIを持ち込まず、execution全体のprocessを回収する。"""

from __future__ import annotations

import asyncio
import ctypes
import os
import signal
import sys
from typing import Any, Protocol


class ProcessContainment(Protocol):
    def attach(self, pid: int) -> None: ...
    def active(self) -> bool: ...
    def terminate(self, process: asyncio.subprocess.Process, *, force: bool) -> None: ...
    def close(self) -> None: ...


class PosixProcessGroup:
    """start_new_sessionで生成したworkerのgroupだけを対象にする。"""

    def __init__(self) -> None:
        self._pgid: int | None = None

    def attach(self, pid: int) -> None:
        self._pgid = pid

    def active(self) -> bool:
        if self._pgid is None:
            return False
        try:
            os.killpg(self._pgid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            # 終了直後の孤児/zombieでもEPERMになり得る。消滅確認にはせず、
            # bounded wait内で再照会し、確認不能が続けばcleanupを失敗させる。
            return True
        return True

    def terminate(self, process: asyncio.subprocess.Process, *, force: bool) -> None:
        if self._pgid is not None:
            try:
                os.killpg(self._pgid, signal.SIGKILL if force else signal.SIGTERM)
            except ProcessLookupError:
                pass

    def close(self) -> None:
        self._pgid = None


class JobApi(Protocol):
    """Windows実機なしでもJobの所有・失敗経路を検証できる境界。"""

    def create(self) -> int: ...
    def assign(self, job: int, pid: int) -> None: ...
    def active_count(self, job: int) -> int: ...
    def terminate(self, job: int) -> None: ...
    def close(self, handle: int) -> None: ...


# Windows ABIの固定幅を使い、非Windows上のnative境界試験でも同じlayoutにする。
class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", ctypes.c_uint64 * 6),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _Accounting(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_int64),
        ("TotalKernelTime", ctypes.c_int64),
        ("ThisPeriodTotalUserTime", ctypes.c_int64),
        ("ThisPeriodTotalKernelTime", ctypes.c_int64),
        ("TotalPageFaultCount", ctypes.c_uint32),
        ("TotalProcesses", ctypes.c_uint32),
        ("ActiveProcesses", ctypes.c_uint32),
        ("TotalTerminatedProcesses", ctypes.c_uint32),
    ]


class WindowsJobApi:
    """Job Objectのnative呼出し。raw OS診断は公開契約へ渡さない。"""

    def __init__(self, library: Any = None) -> None:
        self._dll: Any
        if library is not None:
            self._dll = library
        elif sys.platform == "win32":
            self._dll = ctypes.WinDLL("kernel32", use_last_error=True)
        else:
            raise OSError("Windows Job APIはWindows上でだけ読み込めます")
        handle, dword, boolean = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int
        signatures = {
            "CreateJobObjectW": ([handle, ctypes.c_wchar_p], handle),
            "SetInformationJobObject": ([handle, ctypes.c_int, handle, dword], boolean),
            "OpenProcess": ([dword, boolean, dword], handle),
            "AssignProcessToJobObject": ([handle, handle], boolean),
            "QueryInformationJobObject": ([handle, ctypes.c_int, handle, dword, handle], boolean),
            "TerminateJobObject": ([handle, dword], boolean),
            "CloseHandle": ([handle], boolean),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self._dll, name)
            function.argtypes, function.restype = arguments, result

    @staticmethod
    def _check(result: Any) -> None:
        if not result:
            raise OSError("PresentationのJob Object操作に失敗しました")

    def create(self) -> int:
        job = self._dll.CreateJobObjectW(None, None)
        self._check(job)
        limits = _ExtendedLimits()
        # breakawayを許可せず、親の異常終了にも備えて最後のhandle閉鎖時に全体を終了する。
        limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        try:
            self._check(
                self._dll.SetInformationJobObject(
                    job, 9, ctypes.byref(limits), ctypes.sizeof(limits)
                )
            )
        except OSError:
            self.close(int(job))
            raise
        return int(job)

    def assign(self, job: int, pid: int) -> None:
        # PROCESS_SET_QUOTA | PROCESS_TERMINATE。Adapter command送信より前に割り当てる。
        process = self._dll.OpenProcess(0x0100 | 0x0001, False, pid)
        self._check(process)
        try:
            self._check(self._dll.AssignProcessToJobObject(job, process))
        finally:
            self.close(int(process))

    def active_count(self, job: int) -> int:
        accounting = _Accounting()
        self._check(
            self._dll.QueryInformationJobObject(
                job, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None
            )
        )
        return int(accounting.ActiveProcesses)

    def terminate(self, job: int) -> None:
        self._check(self._dll.TerminateJobObject(job, 1))

    def close(self, handle: int) -> None:
        self._check(self._dll.CloseHandle(handle))


class WindowsJob:
    def __init__(self, api: JobApi) -> None:
        self._api = api
        self._handle: int | None = api.create()
        self._attached = False

    def attach(self, pid: int) -> None:
        assert self._handle is not None
        self._api.assign(self._handle, pid)
        self._attached = True

    def active(self) -> bool:
        return self._handle is not None and self._api.active_count(self._handle) != 0

    def terminate(self, process: asyncio.subprocess.Process, *, force: bool) -> None:
        assert self._handle is not None
        self._api.terminate(self._handle)
        if not self._attached:
            # 割当失敗時だけ、command未送信のbootstrap processを直接回収する。
            try:
                process.kill()
            except ProcessLookupError:
                pass

    def close(self) -> None:
        if self._handle is not None:
            self._api.close(self._handle)
            self._handle = None


def create_containment() -> ProcessContainment:
    if os.name == "posix":
        return PosixProcessGroup()
    if os.name == "nt":
        return WindowsJob(WindowsJobApi())
    raise OSError("このOSにはPresentationのprocess containment実装がありません")
