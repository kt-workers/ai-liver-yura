from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from app.domain.speech_runtime.contracts import (
    AudioReadinessState,
    CandidateLifecycle,
    PresentationTimeoutPhase,
    SpeechPresentationCommand,
    SpeechPresentationMode,
    SpeechPresentationReport,
    SpeechPresentationReportStatus,
    SpeechPresentationTimeoutRecord,
)
from app.domain.speech_runtime.policy import SpeechPresentationTimeoutPolicy
from app.domain.speech_runtime.presentation import SpeechPresentationExecutor
from app.domain.speech_runtime.runtime import SpeechRuntime
from app.domain.speech_runtime.tasks import CandidateTaskKey, CandidateTaskRegistry
from app.subsystems.validation.presentation_session import LocalPresentationBoundary
from tests.domain.speech_runtime.policy_fixtures import runtime_policy
from tests.domain.speech_runtime.test_presentation import _ready_candidate, _state
from tests.infrastructure.speech_presentation.test_process import (
    test_noncooperative_shutdown as verify_noncooperative_shutdown,
)

NOW = datetime(2026, 9, 12, tzinfo=timezone.utc)


@dataclass
class Clock:
    now: datetime = NOW

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


async def committed(
    *, audio: bool = False, duration: int | None = None
) -> tuple[SpeechRuntime, Clock, SpeechPresentationCommand, SpeechPresentationReport]:
    clock = Clock()
    runtime = SpeechRuntime(runtime_policy(), clock)
    candidate = replace(_ready_candidate(), created_at=NOW, updated_at=NOW, prepared_at=NOW)
    state = replace(_state(), observed_at=NOW - timedelta(seconds=20))
    if audio:
        candidate = replace(
            candidate,
            prepared_audio_ref="audio",
            readiness=replace(candidate.readiness, audio=AudioReadinessState.READY),
            presentation_modes=(SpeechPresentationMode.AUDIO_WITH_TEXT,),
        )
        state = replace(
            state,
            prepared_audio_ref="audio",
            prepared_audio_duration_ms=duration,
            capability=replace(state.capability, audio_available=True),
        )
    await runtime.register(candidate)
    command = await runtime.commit("candidate", state, "presentation")
    started = SpeechPresentationReport(
        "presentation",
        "candidate",
        SpeechPresentationReportStatus.STARTED,
        command.modes,
        NOW - timedelta(seconds=10),
        None,
        command.audio_ref,
        None,
    )
    return runtime, clock, command, started


async def expire(runtime: SpeechRuntime) -> CandidateLifecycle:
    return (await runtime.expire_presentation_if_due("presentation", "candidate", 1)).lifecycle


def test_approved_timeout_defaults() -> None:
    policy = runtime_policy().presentation_timeout
    assert policy == SpeechPresentationTimeoutPolicy(5, 5, 5, 60)


@pytest.mark.parametrize(
    "field",
    [
        "start_report_timeout_seconds",
        "text_terminal_timeout_seconds",
        "audio_terminal_grace_seconds",
        "audio_terminal_fallback_timeout_seconds",
    ],
)
@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan"), True, "5"])
def test_invalid_timeout_policy(field: str, value: Any) -> None:
    with pytest.raises(ValueError):
        replace(SpeechPresentationTimeoutPolicy(), **{field: value})


@pytest.mark.asyncio
async def test_start_wait_exact_owner_deadline_without_fake_report() -> None:
    runtime, clock, _, _ = await committed()
    clock.advance(4.999)
    assert await expire(runtime) is CandidateLifecycle.PRESENTING
    clock.advance(0.001)
    assert await expire(runtime) is CandidateLifecycle.FAILED
    assert await runtime.presentation_reports("presentation") == ()
    record = await runtime.presentation_timeout_record("presentation")
    assert record == SpeechPresentationTimeoutRecord(
        "presentation",
        "candidate",
        PresentationTimeoutPhase.START_WAIT,
        NOW + timedelta(seconds=5),
        clock.now,
        runtime_policy().policy_id,
        1,
    )
    clock.advance(20)
    assert await expire(runtime) is CandidateLifecycle.FAILED
    assert await runtime.presentation_timeout_record("presentation") == record


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        SpeechPresentationReportStatus.STARTED,
        SpeechPresentationReportStatus.FAILED_BEFORE_START,
    ],
)
@pytest.mark.parametrize("seconds", [4.999, 5.0, 6.0])
async def test_first_report_race(status: SpeechPresentationReportStatus, seconds: float) -> None:
    runtime, clock, _, report = await committed()
    if status is SpeechPresentationReportStatus.FAILED_BEFORE_START:
        report = replace(report, status=status, started_at=None, completed_at=NOW)
    clock.advance(seconds)
    result = await runtime.accept_report(report)
    if seconds < 5:
        assert await runtime.presentation_reports("presentation") == (report,)
        assert await runtime.presentation_timeout_record("presentation") is None
    else:
        assert result.lifecycle is CandidateLifecycle.FAILED
        assert await runtime.presentation_reports("presentation") == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "audio,duration,seconds",
    [
        (False, None, 5),
        (True, 12000, 17),
        (True, None, 60),
    ],
)
async def test_terminal_deadline_uses_acceptance_and_bound_duration(
    audio: bool,
    duration: int | None,
    seconds: int,
) -> None:
    runtime, clock, _, started = await committed(audio=audio, duration=duration)
    clock.advance(4)
    await runtime.accept_report(started)
    clock.advance(seconds - 0.001)
    assert await expire(runtime) is CandidateLifecycle.PRESENTING
    clock.advance(0.001)
    assert await expire(runtime) is CandidateLifecycle.FAILED
    assert await runtime.presentation_reports("presentation") == (started,)
    record = await runtime.presentation_timeout_record("presentation")
    assert record is not None and record.phase is PresentationTimeoutPhase.TERMINAL_WAIT
    assert record.deadline == NOW + timedelta(seconds=4 + seconds)


@pytest.mark.parametrize("value", [0, -1, True, 1.5, float("inf"), "12000"])
def test_invalid_audio_duration(value: Any) -> None:
    with pytest.raises(ValueError):
        replace(_state(), prepared_audio_ref="audio", prepared_audio_duration_ms=value)


def test_duration_without_ref_rejected() -> None:
    with pytest.raises(ValueError):
        replace(_state(), prepared_audio_duration_ms=12000)


@pytest.mark.asyncio
async def test_duration_ref_must_match_current_candidate() -> None:
    runtime = SpeechRuntime(runtime_policy())
    await runtime.register(_ready_candidate())
    with pytest.raises(ValueError, match="revalidation"):
        await runtime.commit(
            "candidate",
            replace(_state(), prepared_audio_ref="other", prepared_audio_duration_ms=12000),
            "presentation",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        SpeechPresentationReportStatus.COMPLETED,
        SpeechPresentationReportStatus.INTERRUPTED,
        SpeechPresentationReportStatus.FAILED_AFTER_START,
    ],
)
@pytest.mark.parametrize("seconds", [4.999, 5.0, 6.0])
async def test_terminal_report_race(status: SpeechPresentationReportStatus, seconds: float) -> None:
    runtime, clock, _, started = await committed()
    await runtime.accept_report(started)
    clock.advance(seconds)
    terminal = replace(started, status=status, completed_at=NOW)
    await runtime.accept_report(terminal)
    if seconds < 5:
        assert await runtime.presentation_reports("presentation") == (started, terminal)
        assert await runtime.presentation_timeout_record("presentation") is None
        before = await runtime.candidate("candidate")
        clock.advance(100)
        await expire(runtime)
        assert await runtime.candidate("candidate") == before
    else:
        assert await runtime.presentation_reports("presentation") == (started,)
        assert await expire(runtime) is CandidateLifecycle.FAILED


@pytest.mark.asyncio
async def test_concurrent_expiry_report_and_wrong_generation() -> None:
    runtime, clock, _, started = await committed()
    await runtime.accept_report(started)
    with pytest.raises(ValueError, match="generation"):
        await runtime.expire_presentation_if_due("presentation", "candidate", 2)
    with pytest.raises(ValueError, match="identity"):
        await runtime.expire_presentation_if_due("presentation", "other", 1)
    clock.advance(5)
    await asyncio.gather(
        expire(runtime),
        runtime.accept_report(
            replace(started, status=SpeechPresentationReportStatus.COMPLETED, completed_at=NOW)
        ),
        return_exceptions=True,
    )
    assert await expire(runtime) is CandidateLifecycle.FAILED
    assert await runtime.presentation_reports("presentation") == (started,)


@pytest.mark.asyncio
@pytest.mark.parametrize("shutdown", [False, True])
async def test_cancelled_owner_is_not_overwritten(shutdown: bool) -> None:
    runtime, clock, _, started = await committed()
    await runtime.accept_report(started)
    if shutdown:
        await runtime.shutdown()
    else:
        await runtime.cancel("candidate")
    clock.advance(100)
    assert await expire(runtime) is CandidateLifecycle.CANCELLED
    assert await runtime.presentation_timeout_record("presentation") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("duration", [1.0, 50.0])
async def test_active_policy_frozen_and_new_presentation_uses_new_generation(
    duration: float,
) -> None:
    runtime, clock, _, started = await committed()
    new = replace(
        runtime_policy(revision=2),
        presentation_timeout=SpeechPresentationTimeoutPolicy(
            duration, duration, duration, duration
        ),
    )
    await runtime.update_operational_policy(new)
    assert await runtime.presentation_wait_seconds("presentation", "candidate", 1) == 5
    await runtime.accept_report(started)
    assert await runtime.presentation_wait_seconds("presentation", "candidate", 1) == 5
    candidate = replace(
        _ready_candidate(),
        candidate_id="next",
        runtime_policy_revision=2,
        created_at=NOW,
        updated_at=NOW,
        prepared_at=NOW,
    )
    await runtime.register(candidate)
    await runtime.commit("next", replace(_state(), observed_at=NOW), "next")
    assert await runtime.presentation_wait_seconds("next", "next", 1) == duration
    clock.advance(5)
    await expire(runtime)
    record = await runtime.presentation_timeout_record("presentation")
    assert record is not None and record.policy_revision == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("started", [False, True])
async def test_hanging_adapter_reaped_and_other_candidate_progresses(started: bool) -> None:
    policy = replace(
        runtime_policy(),
        presentation_timeout=SpeechPresentationTimeoutPolicy(0.03, 0.03, 0.03, 0.03),
    )
    runtime, tasks = SpeechRuntime(policy), CandidateTaskRegistry()
    await runtime.register(_ready_candidate())
    entered, cleaned, other_done, other_release = (asyncio.Event() for _ in range(4))

    async def adapter(
        command: SpeechPresentationCommand,
    ) -> AsyncIterator[SpeechPresentationReport]:
        try:
            if started:
                yield SpeechPresentationReport(
                    command.presentation_id,
                    command.candidate_id,
                    SpeechPresentationReportStatus.STARTED,
                    command.modes,
                    datetime.now(timezone.utc),
                    None,
                    command.audio_ref,
                    None,
                )
            entered.set()
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    async def other() -> object:
        await runtime.register(replace(_ready_candidate(), candidate_id="other"))
        other_done.set()
        await other_release.wait()
        return None

    other_task = tasks.start(CandidateTaskKey("other", 1, "preparation"), other())
    await SpeechPresentationExecutor(runtime, tasks).commit_and_present(
        candidate_id="candidate",
        state=_state(),
        presentation_id="presentation",
        adapter=LocalPresentationBoundary(adapter),
    )

    async def finish() -> None:
        await entered.wait()
        await other_done.wait()
        await cleaned.wait()
        while tasks.pending_task_count > 1:
            await asyncio.sleep(0)

    await asyncio.wait_for(finish(), 1)
    assert await expire(runtime) is CandidateLifecycle.FAILED
    assert not other_task.done()
    other_release.set()
    await other_task
    assert tasks.pending_task_count == 0


@pytest.mark.asyncio
async def test_cancellation_ignoring_adapter_does_not_hold_shutdown(tmp_path: Path) -> None:
    """旧同一process失敗条件を実worker境界で検証する。"""
    await verify_noncooperative_shutdown(tmp_path)


@pytest.mark.asyncio
async def test_start_wait_timeout_has_no_actual_fact() -> None:
    from app.composition.execution_observation import project_speech_execution_observation
    from tests.system_integration.test_execution_observation_boundary import PROVENANCE

    runtime, clock, _, _ = await committed()
    clock.advance(5)
    await expire(runtime)
    assert await project_speech_execution_observation(runtime, "presentation", PROVENANCE) is None
