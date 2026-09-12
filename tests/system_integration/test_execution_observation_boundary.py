from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Coroutine
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.composition.execution_observation import (
    SPEECH_OBSERVATION_POLICY,
    project_speech_execution_observation,
)
from app.domain.activity_execution import ActivityExecutionAuthority, ExecutionObservationProvenance
from app.domain.contracts import ExecutionStatus, RevisionVector
from app.domain.speech_runtime.contracts import (
    AudioReadinessState,
    CandidateLifecycle,
    PreparedSpeechCandidate,
    SpeechPresentationCommand,
    SpeechPresentationMode,
    SpeechPresentationReport,
    SpeechPresentationReportStatus,
)
from app.domain.speech_runtime.presentation import SpeechPresentationExecutor
from app.domain.speech_runtime.runtime import SpeechRuntime
from app.domain.speech_runtime.tasks import CandidateTaskKey, CandidateTaskRegistry
from app.subsystems.validation.presentation_session import LocalPresentationBoundary
from tests.domain.speech_runtime.policy_fixtures import runtime_policy
from tests.domain.speech_runtime.test_presentation import _ready_candidate, _state

NOW = datetime(2026, 9, 12, tzinfo=timezone.utc)
PROVENANCE = ExecutionObservationProvenance(
    "decision", ("event",), RevisionVector(1, 1, 1), "trace"
)


async def presentation(
    audio: bool = False,
) -> tuple[SpeechRuntime, SpeechPresentationCommand, SpeechPresentationReport]:
    runtime = SpeechRuntime(runtime_policy(), clock=lambda: NOW + timedelta(seconds=2))
    candidate = replace(_ready_candidate(), created_at=NOW, updated_at=NOW, prepared_at=NOW)
    state = replace(_state(), observed_at=NOW)
    if audio:
        candidate = replace(
            candidate,
            prepared_audio_ref="audio",
            presentation_modes=(SpeechPresentationMode.AUDIO_WITH_TEXT,),
            readiness=replace(candidate.readiness, audio=AudioReadinessState.READY),
        )
        state = replace(
            state,
            capability=replace(state.capability, audio_available=True),
            prepared_audio_ref="audio",
        )
    await runtime.register(candidate)
    command = await runtime.commit("candidate", state, "presentation")
    report = SpeechPresentationReport(
        command.presentation_id,
        command.candidate_id,
        SpeechPresentationReportStatus.STARTED,
        command.modes,
        NOW + timedelta(seconds=1),
        None,
        command.audio_ref,
        None,
    )
    return runtime, command, report


@pytest.mark.asyncio
@pytest.mark.parametrize("audio", [False, True])
@pytest.mark.parametrize(
    "status,expected",
    [
        (SpeechPresentationReportStatus.COMPLETED, ExecutionStatus.COMPLETED),
        (SpeechPresentationReportStatus.INTERRUPTED, ExecutionStatus.CANCELLED),
        (SpeechPresentationReportStatus.FAILED_AFTER_START, ExecutionStatus.FAILED),
    ],
)
async def test_closed_mapping_preserves_partial_effects(
    audio: bool, status: SpeechPresentationReportStatus, expected: ExecutionStatus
) -> None:
    runtime, command, started = await presentation(audio)
    await runtime.accept_report(started)
    observation = await project_speech_execution_observation(
        runtime, command.presentation_id, PROVENANCE
    )
    assert observation is not None and observation.status is ExecutionStatus.OBSERVABLE
    assert [e.effect_type for e in observation.effects] == (
        ["text-presentation", "audio-presentation-started"] if audio else ["text-presentation"]
    )
    assert observation.provenance is PROVENANCE
    owner = ActivityExecutionAuthority(observation_policy=SPEECH_OBSERVATION_POLICY)

    record = owner.ingest_observation(
        observation, policy_id=SPEECH_OBSERVATION_POLICY.policy_id, policy_revision=1
    )
    assert (
        owner.ingest_observation(
            observation, policy_id=SPEECH_OBSERVATION_POLICY.policy_id, policy_revision=1
        )
        is record
    )
    terminal = replace(
        started,
        status=status,
        completed_at=NOW + timedelta(seconds=2),
        interruption_reason="private raw reason",
        failure_code="private raw failure",
    )
    await runtime.accept_report(terminal)
    projected = await project_speech_execution_observation(
        runtime, command.presentation_id, PROVENANCE
    )
    assert projected is not None and projected.effects == () and projected.status is expected
    assert "private raw" not in repr(projected)
    result = owner.ingest_observation(
        projected, policy_id=SPEECH_OBSERVATION_POLICY.policy_id, policy_revision=1
    )
    assert result.result.effect_refs == record.result.effect_refs
    assert result.effects == record.effects
    assert result.result.occurred_at == terminal.completed_at
    if status is SpeechPresentationReportStatus.INTERRUPTED:
        assert result.result.details == {"code": "interrupted"}
    with pytest.raises(ValueError):
        ActivityExecutionAuthority(observation_policy=SPEECH_OBSERVATION_POLICY).ingest_observation(
            projected, policy_id=SPEECH_OBSERVATION_POLICY.policy_id, policy_revision=1
        )


@pytest.mark.asyncio
async def test_failed_before_start_has_no_fact() -> None:
    runtime, command, report = await presentation()
    report = replace(
        report,
        status=SpeechPresentationReportStatus.FAILED_BEFORE_START,
        started_at=None,
        completed_at=NOW,
    )
    await runtime.accept_report(report)
    assert (
        await project_speech_execution_observation(runtime, command.presentation_id, PROVENANCE)
        is None
    )


def override_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    runtime: SpeechRuntime,
    snapshot: tuple[
        SpeechPresentationCommand, PreparedSpeechCandidate, tuple[SpeechPresentationReport, ...]
    ],
) -> None:
    async def read(
        presentation_id: str,
    ) -> tuple[
        SpeechPresentationCommand, PreparedSpeechCandidate, tuple[SpeechPresentationReport, ...]
    ]:
        assert presentation_id == "presentation"
        return snapshot

    monkeypatch.setattr(runtime, "presentation_snapshot", read)


@pytest.mark.asyncio
async def test_no_report_has_no_fact() -> None:
    runtime, command, _ = await presentation()
    assert (
        await runtime.candidate(command.candidate_id)
    ).lifecycle is CandidateLifecycle.PRESENTING
    assert (
        await project_speech_execution_observation(runtime, command.presentation_id, PROVENANCE)
        is None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mismatch", ["command", "asset", "candidate", "revision", "events", "decision"]
)
async def test_unaccepted_or_mismatched_input_rejected(
    mismatch: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, command, report = await presentation()
    await runtime.accept_report(report)
    _, candidate, _ = await runtime.presentation_snapshot(command.presentation_id)
    provenance = PROVENANCE
    if mismatch == "command":
        command = replace(command, presentation_id="other")
    elif mismatch == "asset":
        report = replace(report, audio_ref="other")
    elif mismatch == "candidate":
        report = replace(report, candidate_id="other")
    elif mismatch == "revision":
        provenance = replace(PROVENANCE, revisions=RevisionVector(2))
    elif mismatch == "events":
        provenance = replace(PROVENANCE, source_event_ids=("other",))
    elif mismatch == "decision":
        provenance = replace(PROVENANCE, source_decision_id="other")
    override_snapshot(monkeypatch, runtime, (command, candidate, (report,)))
    with pytest.raises(ValueError):
        await project_speech_execution_observation(runtime, "presentation", provenance)


@pytest.mark.asyncio
async def test_missing_started_owner_time_rejected() -> None:
    runtime, command, report = await presentation()
    report = replace(report, started_at=None)
    await runtime.accept_report(report)
    with pytest.raises(ValueError):
        await project_speech_execution_observation(runtime, command.presentation_id, PROVENANCE)


@pytest.mark.asyncio
async def test_owner_fallback_timestamp_and_started_consistency() -> None:
    runtime, command, report = await presentation()
    await runtime.accept_report(report)
    terminal = replace(report, status=SpeechPresentationReportStatus.COMPLETED)
    candidate = await runtime.accept_report(terminal)
    projected = await project_speech_execution_observation(
        runtime, command.presentation_id, PROVENANCE
    )
    assert projected is not None and projected.occurred_at == candidate.updated_at
    runtime, command, report = await presentation()
    await runtime.accept_report(report)
    terminal = replace(
        report,
        status=SpeechPresentationReportStatus.COMPLETED,
        started_at=NOW + timedelta(seconds=2),
        completed_at=NOW + timedelta(seconds=3),
    )
    await runtime.accept_report(terminal)
    with pytest.raises(ValueError):
        await project_speech_execution_observation(runtime, command.presentation_id, PROVENANCE)


class CapturingTasks(CandidateTaskRegistry):
    """実Executorが登録したtaskの終了結果を試験で回収する。"""

    task: asyncio.Task[object] | None = None

    def start(
        self, key: CandidateTaskKey, work: Coroutine[Any, Any, object]
    ) -> asyncio.Task[object]:
        self.task = super().start(key, work)
        return self.task


@pytest.mark.asyncio
async def test_started_only_executor_failure_closes_actual_fact() -> None:
    now = NOW
    runtime = SpeechRuntime(runtime_policy(), clock=lambda: now)
    await runtime.register(
        replace(_ready_candidate(), created_at=NOW, updated_at=NOW, prepared_at=NOW)
    )
    tasks = CapturingTasks()
    accepted, release = asyncio.Event(), asyncio.Event()
    started = SpeechPresentationReport(
        "presentation",
        "candidate",
        SpeechPresentationReportStatus.STARTED,
        (SpeechPresentationMode.TEXT_ONLY,),
        NOW + timedelta(seconds=1),
        None,
        None,
        None,
    )

    async def adapter(
        command: SpeechPresentationCommand,
    ) -> AsyncIterator[SpeechPresentationReport]:
        assert command.presentation_id == started.presentation_id
        yield started
        accepted.set()
        await release.wait()

    command = await SpeechPresentationExecutor(runtime, tasks).commit_and_present(
        candidate_id="candidate",
        state=replace(_state(), observed_at=NOW),
        presentation_id="presentation",
        adapter=LocalPresentationBoundary(adapter),
    )
    assert tasks.task is not None
    owner = ActivityExecutionAuthority(observation_policy=SPEECH_OBSERVATION_POLICY)
    try:
        await accepted.wait()
        observation = await project_speech_execution_observation(
            runtime, command.presentation_id, PROVENANCE
        )
        assert observation is not None and observation.status is ExecutionStatus.OBSERVABLE
        before = owner.ingest_observation(
            observation, policy_id=SPEECH_OBSERVATION_POLICY.policy_id, policy_revision=1
        )
        now = NOW + timedelta(seconds=2)
        release.set()
        with pytest.raises(ValueError, match="terminal report"):
            await tasks.task
        _, candidate, reports = await runtime.presentation_snapshot("presentation")
        assert candidate.lifecycle is CandidateLifecycle.FAILED and reports == (started,)
        terminal = await project_speech_execution_observation(
            runtime, command.presentation_id, PROVENANCE
        )
        assert terminal is not None and terminal.status is ExecutionStatus.FAILED
        assert terminal.effects == ()
        after = owner.ingest_observation(
            terminal, policy_id=SPEECH_OBSERVATION_POLICY.policy_id, policy_revision=1
        )
        assert after.result.status is ExecutionStatus.FAILED
        assert after.result.effect_refs == before.result.effect_refs
        assert (
            after.effects == before.effects
            and after.effect_uncertainty == before.effect_uncertainty
        )
        assert after.result.details == {"code": "presentation_owner_failed_after_start"}
        assert after.result.occurred_at == candidate.updated_at == now
        assert await runtime.presentation_reports("presentation") == (started,)
    finally:
        release.set()
        await asyncio.gather(tasks.task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        SpeechPresentationReportStatus.COMPLETED,
        SpeechPresentationReportStatus.INTERRUPTED,
        SpeechPresentationReportStatus.FAILED_AFTER_START,
    ],
)
async def test_terminal_report_requires_matching_current_lifecycle(
    status: SpeechPresentationReportStatus, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, command, started = await presentation()
    await runtime.accept_report(started)
    terminal = replace(started, status=status, completed_at=NOW + timedelta(seconds=2))
    await runtime.accept_report(terminal)
    _, candidate, reports = await runtime.presentation_snapshot(command.presentation_id)
    override_snapshot(
        monkeypatch,
        runtime,
        (command, replace(candidate, lifecycle=CandidateLifecycle.PRESENTING), reports),
    )
    with pytest.raises(ValueError, match="lifecycle"):
        await project_speech_execution_observation(runtime, command.presentation_id, PROVENANCE)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "shape",
    [
        (SpeechPresentationReportStatus.COMPLETED,),
        (SpeechPresentationReportStatus.INTERRUPTED,),
        (SpeechPresentationReportStatus.FAILED_AFTER_START,),
        (SpeechPresentationReportStatus.STARTED, SpeechPresentationReportStatus.STARTED),
        (
            SpeechPresentationReportStatus.FAILED_BEFORE_START,
            SpeechPresentationReportStatus.STARTED,
        ),
        (
            SpeechPresentationReportStatus.STARTED,
            SpeechPresentationReportStatus.COMPLETED,
            SpeechPresentationReportStatus.INTERRUPTED,
        ),
    ],
)
async def test_malformed_report_history_is_rejected(
    shape: tuple[SpeechPresentationReportStatus, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, command, started = await presentation()
    candidate = await runtime.accept_report(started)
    reports = tuple(replace(started, status=status) for status in shape)
    override_snapshot(monkeypatch, runtime, (command, candidate, reports))
    with pytest.raises(ValueError, match="系列"):
        await project_speech_execution_observation(runtime, command.presentation_id, PROVENANCE)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "lifecycle",
    [CandidateLifecycle.PRESENTING, CandidateLifecycle.FAILED, CandidateLifecycle.CANCELLED],
)
async def test_snapshot_owner_timestamp_inversion_rejected(
    lifecycle: CandidateLifecycle, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, command, started = await presentation()
    candidate = await runtime.accept_report(started)
    override_snapshot(
        monkeypatch,
        runtime,
        (command, replace(candidate, lifecycle=lifecycle, updated_at=NOW), (started,)),
    )
    with pytest.raises(ValueError, match="時刻"):
        await project_speech_execution_observation(runtime, command.presentation_id, PROVENANCE)


@pytest.mark.asyncio
@pytest.mark.parametrize("audio", [False, True])
async def test_owner_cancelled_snapshot_preserves_started_effects(audio: bool) -> None:
    runtime, command, started = await presentation(audio)
    await runtime.accept_report(started)
    owner = ActivityExecutionAuthority(observation_policy=SPEECH_OBSERVATION_POLICY)
    observation = await project_speech_execution_observation(
        runtime, command.presentation_id, PROVENANCE
    )
    assert observation is not None
    repeated = await project_speech_execution_observation(
        runtime, command.presentation_id, PROVENANCE
    )
    assert repeated == observation
    before = owner.ingest_observation(
        observation, policy_id=SPEECH_OBSERVATION_POLICY.policy_id, policy_revision=1
    )
    assert repeated is not None
    assert (
        owner.ingest_observation(
            repeated, policy_id=SPEECH_OBSERVATION_POLICY.policy_id, policy_revision=1
        )
        is before
    )
    if audio:
        candidate = await runtime.candidate(command.candidate_id)
        await runtime.commit_generation_result(
            command.candidate_id,
            runtime.generation(command.candidate_id),
            readiness=replace(candidate.readiness, audio=AudioReadinessState.DISCARDED),
            clear_prepared_audio=True,
        )
    cancelled = await runtime.cancel(command.candidate_id)
    assert cancelled is not None and cancelled.lifecycle is CandidateLifecycle.CANCELLED
    terminal = await project_speech_execution_observation(
        runtime, command.presentation_id, PROVENANCE
    )
    assert (
        terminal is not None
        and terminal.status is ExecutionStatus.CANCELLED
        and not terminal.effects
    )
    assert terminal.details == {"code": "presentation_owner_cancelled_after_start"}
    after = owner.ingest_observation(
        terminal, policy_id=SPEECH_OBSERVATION_POLICY.policy_id, policy_revision=1
    )
    assert after.result.effect_refs == before.result.effect_refs and after.effects == before.effects
    assert after.result.occurred_at == cancelled.updated_at
    repeated = await project_speech_execution_observation(
        runtime, command.presentation_id, PROVENANCE
    )
    assert repeated == terminal and repeated is not None
    assert (
        owner.ingest_observation(
            repeated, policy_id=SPEECH_OBSERVATION_POLICY.policy_id, policy_revision=1
        )
        is after
    )
    assert await runtime.presentation_reports(command.presentation_id) == (started,)
