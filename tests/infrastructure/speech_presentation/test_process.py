from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from app.domain.speech_runtime.contracts import CandidateLifecycle, SpeechPresentationReportStatus
from app.domain.speech_runtime.policy import SpeechPresentationTimeoutPolicy
from app.domain.speech_runtime.presentation import SpeechPresentationExecutor
from app.domain.speech_runtime.runtime import SpeechRuntime
from app.domain.speech_runtime.tasks import CandidateTaskRegistry
from app.infrastructure.speech_presentation.supervisor import (
    PresentationWorkerRegistration,
    SpeechPresentationWorkerSupervisor,
)
from tests.domain.speech_runtime.policy_fixtures import runtime_policy
from tests.domain.speech_runtime.test_presentation import _ready_candidate, _state


def boundary(
    kind: str, pid_file: Path | None = None, executable: str = sys.executable
) -> SpeechPresentationWorkerSupervisor:
    return SpeechPresentationWorkerSupervisor(
        PresentationWorkerRegistration(
            kind,
            "tests.infrastructure.speech_presentation.worker_fixture",
            "build",
            {} if pid_file is None else {"pid_file": str(pid_file)},
        ),
        executable=executable,
    )


def policy() -> SpeechPresentationTimeoutPolicy:
    return SpeechPresentationTimeoutPolicy(2, 0.1, 0.1, 0.1, 0.03, 0.05, 0.3)


async def run_case(
    kind: str, pid_file: Path | None = None
) -> tuple[SpeechRuntime, SpeechPresentationWorkerSupervisor]:
    runtime = SpeechRuntime(replace(runtime_policy(), presentation_timeout=policy()))
    tasks = CandidateTaskRegistry()
    worker = boundary(kind, pid_file)
    await runtime.register(_ready_candidate())
    await SpeechPresentationExecutor(runtime, tasks).commit_and_present(
        candidate_id="candidate", state=_state(), presentation_id="presentation", adapter=worker
    )

    async def finish() -> None:
        while tasks.pending_task_count:
            await asyncio.sleep(0.001)

    await asyncio.wait_for(finish(), 5)
    assert worker.active_execution_count == 0
    assert tasks.pending_task_count == 0
    if pid_file is not None and os.name == "posix":
        pid = int(pid_file.read_text())
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    return runtime, worker


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,lifecycle,count",
    [
        ("normal", CandidateLifecycle.COMPLETED, 2),
        ("stdout_noise", CandidateLifecycle.COMPLETED, 2),
        ("failed_before", CandidateLifecycle.FAILED, 1),
        ("failed_after", CandidateLifecycle.FAILED, 2),
        ("exit_before", CandidateLifecycle.FAILED, 0),
        ("exit_after", CandidateLifecycle.FAILED, 1),
        ("missing", CandidateLifecycle.FAILED, 1),
        ("wrong_identity", CandidateLifecycle.FAILED, 1),
        ("hang", CandidateLifecycle.FAILED, 1),
    ],
)
async def test_process_paths(
    kind: str, lifecycle: CandidateLifecycle, count: int, tmp_path: Path
) -> None:
    runtime, _ = await run_case(kind, tmp_path / "pid")
    assert (await runtime.candidate("candidate")).lifecycle is lifecycle
    assert len(await runtime.presentation_reports("presentation")) == count


@pytest.mark.asyncio
async def test_noncooperative_shutdown(tmp_path: Path) -> None:
    runtime = SpeechRuntime(replace(runtime_policy(), presentation_timeout=policy()))
    tasks = CandidateTaskRegistry()
    pid_file = tmp_path / "pid"
    worker = boundary("hang", pid_file)
    await runtime.register(_ready_candidate())
    await SpeechPresentationExecutor(runtime, tasks).commit_and_present(
        candidate_id="candidate", state=_state(), presentation_id="presentation", adapter=worker
    )

    async def started() -> None:
        while not await runtime.presentation_reports("presentation"):
            await asyncio.sleep(0.001)

    await asyncio.wait_for(started(), 3)
    closing = asyncio.create_task(tasks.shutdown())
    await asyncio.sleep(0)
    closing.cancel()
    await asyncio.gather(closing, return_exceptions=True)
    await tasks.shutdown()
    await runtime.shutdown()
    assert worker.active_execution_count == 0
    assert tasks.pending_task_count == 0
    if os.name == "posix":
        with pytest.raises(ProcessLookupError):
            os.kill(int(pid_file.read_text()), 0)
    assert (await runtime.candidate("candidate")).lifecycle is CandidateLifecycle.CANCELLED


@pytest.mark.asyncio
async def test_kill_fallback(tmp_path: Path) -> None:
    kind = "ignore_terminate" if os.name == "posix" else "hang"
    await run_case(kind, tmp_path / "pid")


@pytest.mark.asyncio
async def test_repeated_execution(tmp_path: Path) -> None:
    for i in range(3):
        await run_case("normal", tmp_path / str(i))


@pytest.mark.asyncio
async def test_spawn_failure_no_fallback() -> None:
    from app.domain.speech_runtime.execution import (
        PresentationExecutionError,
        PresentationExecutionFailureCode,
    )
    from tests.domain.speech_runtime.test_presentation_timeout import committed

    _, _, command, _ = await committed()
    worker = boundary("normal", executable="/missing/presentation-worker")
    session = worker.open(command, policy())
    with pytest.raises(PresentationExecutionError) as error:
        await session.receive()
    assert error.value.code is PresentationExecutionFailureCode.SPAWN_FAILED
    await session.close()
    assert worker.active_execution_count == 0 and session.diagnostics.pid is None


@pytest.mark.asyncio
async def test_normal_exit_and_kill_diagnostics() -> None:
    from tests.domain.speech_runtime.test_presentation_timeout import committed

    for kind in ("normal", "ignore_terminate" if os.name == "posix" else "hang"):
        _, _, command, _ = await committed()
        worker = boundary(kind)
        session = worker.open(command, policy())
        assert (await session.receive()).status is SpeechPresentationReportStatus.STARTED
        if kind == "normal":
            assert (await session.receive()).status is SpeechPresentationReportStatus.COMPLETED
        await session.close()
        assert session.diagnostics.closed and session.diagnostics.returncode is not None
        if kind == "normal":
            assert session.diagnostics.returncode == 0
            assert not session.diagnostics.killed
        elif os.name == "posix":
            assert session.diagnostics.terminated and session.diagnostics.killed
        assert worker.active_execution_count == 0


@pytest.mark.asyncio
async def test_session_repeated_cancellation_reaps() -> None:
    from tests.domain.speech_runtime.test_presentation_timeout import committed

    _, _, command, _ = await committed()
    worker = boundary("ignore_terminate" if os.name == "posix" else "hang")
    session = worker.open(command, policy())
    await session.receive()
    closing = asyncio.create_task(session.close())
    for _ in range(3):
        await asyncio.sleep(0.001)
        closing.cancel()
    await asyncio.gather(closing, return_exceptions=True)
    assert session.diagnostics.closed and worker.active_execution_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("audio", [False, True])
async def test_timeout_preserves_fact_and_unrelated_progress(tmp_path: Path, audio: bool) -> None:
    from app.composition.execution_observation import (
        SPEECH_OBSERVATION_POLICY,
        project_speech_execution_observation,
    )
    from app.domain.activity_execution import ActivityExecutionAuthority
    from app.domain.contracts import ExecutionStatus
    from tests.system_integration.test_execution_observation_boundary import PROVENANCE

    runtime = SpeechRuntime(replace(runtime_policy(), presentation_timeout=policy()))
    tasks = CandidateTaskRegistry()
    worker = boundary("hang", tmp_path / "pid")
    from app.domain.speech_runtime.contracts import AudioReadinessState, SpeechPresentationMode

    candidate, state = _ready_candidate(), _state()
    if audio:
        candidate = replace(
            candidate,
            prepared_audio_ref="audio",
            presentation_modes=(SpeechPresentationMode.AUDIO_WITH_TEXT,),
            readiness=replace(candidate.readiness, audio=AudioReadinessState.READY),
        )
        state = replace(
            state,
            prepared_audio_ref="audio",
            capability=replace(state.capability, audio_available=True),
        )
    await runtime.register(candidate)
    await SpeechPresentationExecutor(runtime, tasks).commit_and_present(
        candidate_id="candidate", state=state, presentation_id="presentation", adapter=worker
    )

    async def started() -> None:
        while not await runtime.presentation_reports("presentation"):
            await asyncio.sleep(0.001)

    await asyncio.wait_for(started(), 3)
    before = await project_speech_execution_observation(runtime, "presentation", PROVENANCE)
    assert before is not None and before.status is ExecutionStatus.OBSERVABLE
    assert len(before.effects) == (2 if audio else 1)
    owner = ActivityExecutionAuthority(observation_policy=SPEECH_OBSERVATION_POLICY)
    first = owner.ingest_observation(
        before, policy_id=SPEECH_OBSERVATION_POLICY.policy_id, policy_revision=1
    )
    await runtime.register(replace(_ready_candidate(), candidate_id="unrelated"))
    assert (await runtime.candidate("unrelated")).lifecycle is CandidateLifecycle.READY_TO_PRESENT

    async def finished() -> None:
        while tasks.pending_task_count:
            await asyncio.sleep(0.001)

    await asyncio.wait_for(finished(), 3)
    after = await project_speech_execution_observation(runtime, "presentation", PROVENANCE)
    assert after is not None and after.status is ExecutionStatus.FAILED and not after.effects
    final = owner.ingest_observation(
        after, policy_id=SPEECH_OBSERVATION_POLICY.policy_id, policy_revision=1
    )
    assert final.effects == first.effects
    assert final.result.effect_refs == first.result.effect_refs
    assert worker.active_execution_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("line", [b"not-json\n", b'{"version":99}\n', b"x" * 65537 + b"\n"])
async def test_malformed_actual_pipe_is_reaped(
    line: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.domain.speech_runtime.execution import PresentationExecutionError
    from app.domain.speech_runtime.execution import PresentationExecutionFailureCode as Code
    from tests.domain.speech_runtime.test_presentation_timeout import committed

    original = asyncio.create_subprocess_exec

    async def spawn(*args: Any, **kwargs: Any) -> asyncio.subprocess.Process:
        return await original(
            sys.executable,
            "-c",
            "import sys;sys.stdin.buffer.readline();sys.stdout.buffer.write("
            + repr(line)
            + ");sys.stdout.flush()",
            **kwargs,
        )

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    _, _, command, _ = await committed()
    worker = boundary("normal")
    session = worker.open(command, policy())
    try:
        with pytest.raises(PresentationExecutionError) as error:
            await session.receive()
        assert error.value.code is Code.PROTOCOL_INVALID
    finally:
        await session.close()
    assert session.diagnostics.closed and session.diagnostics.returncode is not None
    assert worker.active_execution_count == 0


@pytest.mark.asyncio
async def test_cancel_during_spawn_reaps(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.domain.speech_runtime.test_presentation_timeout import committed

    original = asyncio.create_subprocess_exec
    spawned, release = asyncio.Event(), asyncio.Event()

    async def spawn(*args: Any, **kwargs: Any) -> asyncio.subprocess.Process:
        process = await original(*args, **kwargs)
        spawned.set()
        await release.wait()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    _, _, command, _ = await committed()
    worker = boundary("hang")
    session = worker.open(command, policy())
    read = asyncio.create_task(session.receive())
    await asyncio.wait_for(spawned.wait(), 2)
    read.cancel()
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(read, return_exceptions=True)
    await session.close()
    assert session.diagnostics.closed and worker.active_execution_count == 0
