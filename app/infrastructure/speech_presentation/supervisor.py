"""1 Presentationごとの子worker・pipe・回収を所有する親側Supervisor。"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass, field

from app.domain.contracts.common import JsonValue, freeze_json, require_identifier, thaw_json
from app.domain.speech_runtime.contracts import (
    SpeechPresentationCommand,
    SpeechPresentationReport,
    SpeechPresentationReportStatus,
)
from app.domain.speech_runtime.execution import PresentationExecutionError
from app.domain.speech_runtime.execution import PresentationExecutionFailureCode as Code
from app.domain.speech_runtime.policy import SpeechPresentationTimeoutPolicy

from .codec import MAX_MESSAGE_BYTES, command_payload, encode, parse_report


@dataclass(frozen=True)
class PresentationWorkerRegistration:
    """信頼された構成側だけが指定する子内factoryの登録。callableは搬送しない。"""

    adapter_kind: str
    factory_module: str
    factory_name: str
    configuration: JsonValue

    def __post_init__(self) -> None:
        for name in ("adapter_kind", "factory_module", "factory_name"):
            require_identifier(getattr(self, name), name)
        if (
            not all(p.isidentifier() for p in self.factory_module.split("."))
            or not self.factory_name.isidentifier()
        ):
            raise ValueError("worker factoryの識別子が不正です")
        object.__setattr__(self, "configuration", freeze_json(self.configuration))


@dataclass
class PresentationWorkerDiagnostics:
    pid: int | None = None
    returncode: int | None = None
    failure: Code | None = None
    terminated: bool = False
    killed: bool = False
    closed: bool = False


class SpeechPresentationWorkerSupervisor:
    def __init__(
        self, registration: PresentationWorkerRegistration, *, executable: str = sys.executable
    ) -> None:
        self.registration = registration
        self.executable = executable
        self._sessions: set[PresentationWorkerSession] = set()

    @property
    def active_execution_count(self) -> int:
        return len(self._sessions)

    def open(
        self, command: SpeechPresentationCommand, policy: SpeechPresentationTimeoutPolicy
    ) -> PresentationWorkerSession:
        session = PresentationWorkerSession(self, command, policy)
        self._sessions.add(session)
        return session


@dataclass(eq=False)
class PresentationWorkerSession:
    supervisor: SpeechPresentationWorkerSupervisor
    command: SpeechPresentationCommand
    policy: SpeechPresentationTimeoutPolicy
    diagnostics: PresentationWorkerDiagnostics = field(
        default_factory=PresentationWorkerDiagnostics
    )
    _process: asyncio.subprocess.Process | None = None
    _started: bool = False
    _closing: asyncio.Task[None] | None = None

    async def _launch(self) -> None:
        registration = self.supervisor.registration
        try:
            data = encode(
                "command",
                self.command,
                dict(
                    command=command_payload(self.command),
                    adapter_kind=registration.adapter_kind,
                    factory_module=registration.factory_module,
                    factory_name=registration.factory_name,
                    configuration=thaw_json(registration.configuration),
                ),
            )
            # 実環境のcredentialやPython起動hookを子へ引き継がない。
            environment = {
                key: os.environ[key]
                for key in ("PATH", "SYSTEMROOT", "WINDIR", "TMPDIR", "TEMP", "TMP", "LANG")
                if key in os.environ
            }
            birth = asyncio.create_task(
                asyncio.create_subprocess_exec(
                    self.supervisor.executable,
                    "-m",
                    "app.infrastructure.speech_presentation.worker",
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    env=environment,
                    limit=MAX_MESSAGE_BYTES,
                )
            )
            cancelled = False
            while True:
                try:
                    self._process = await asyncio.shield(birth)
                    break
                except asyncio.CancelledError:
                    cancelled = True
            self.diagnostics.pid = self._process.pid
            if cancelled:
                raise asyncio.CancelledError
            assert self._process.stdin is not None
            self._process.stdin.write(data)
            await self._process.stdin.drain()
        except PresentationExecutionError as exc:
            self.diagnostics.failure = exc.code
            raise
        except OSError:
            self.diagnostics.failure = Code.SPAWN_FAILED
            raise PresentationExecutionError(Code.SPAWN_FAILED) from None

    async def receive(self) -> SpeechPresentationReport:
        try:
            if self.diagnostics.closed:
                raise PresentationExecutionError(Code.TERMINAL_MISSING)
            if self._process is None:
                await self._launch()
            assert self._process is not None and self._process.stdout is not None
            try:
                line = await self._process.stdout.readline()
            except (ValueError, asyncio.LimitOverrunError):
                raise PresentationExecutionError(Code.PROTOCOL_INVALID) from None
            if not line:
                # EOF後もOS終了を無期限には待たず、回収後の終了コードを照合する。
                await self.close()
                code = Code.EXIT_AFTER_START if self._started else Code.EXIT_BEFORE_START
                if self._process.returncode == 0:
                    code = Code.TERMINAL_MISSING
                raise PresentationExecutionError(code)
            report = parse_report(line, self.command)
            self._started |= report.status is SpeechPresentationReportStatus.STARTED
            return report
        except PresentationExecutionError as exc:
            self.diagnostics.failure = exc.code
            raise

    async def close(self) -> None:
        if self._closing is None:
            self._closing = asyncio.create_task(self._cleanup())
        cancelled = False
        while True:
            try:
                await asyncio.shield(self._closing)
                break
            except asyncio.CancelledError:
                cancelled = True
        if cancelled:
            raise asyncio.CancelledError

    async def _cleanup(self) -> None:
        process = self._process
        if process is not None:
            if process.stdin is not None:
                process.stdin.close()

            async def drain_output() -> None:
                if process.stdout is not None:
                    while await process.stdout.read(8192):
                        pass

            drain = asyncio.create_task(drain_output())

            async def exited(seconds: float) -> bool:
                try:
                    await asyncio.wait_for(process.wait(), seconds)
                    return True
                except asyncio.TimeoutError:
                    return False

            if not await exited(self.policy.worker_grace_seconds):
                self.diagnostics.terminated = True
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
                if not await exited(self.policy.worker_terminate_seconds):
                    self.diagnostics.killed = True
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                    if not await exited(self.policy.worker_kill_seconds):
                        drain.cancel()
                        await asyncio.gather(drain, return_exceptions=True)
                        self.diagnostics.failure = Code.CLEANUP_FAILED
                        raise PresentationExecutionError(Code.CLEANUP_FAILED)
            self.diagnostics.returncode = process.returncode
            if process.stdin is not None:
                try:
                    await asyncio.wait_for(
                        process.stdin.wait_closed(), self.policy.worker_kill_seconds
                    )
                except (BrokenPipeError, ConnectionResetError):
                    pass
            await asyncio.wait_for(drain, self.policy.worker_kill_seconds)
        self.diagnostics.closed = True
        self.supervisor._sessions.discard(self)
