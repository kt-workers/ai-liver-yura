from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app.composition.execution_observation import (
    SPEECH_OBSERVATION_POLICY,
    project_speech_execution_observation,
)
from app.domain.activity_execution import ActivityExecutionAuthority, ExecutionObservationProvenance
from app.domain.contracts import ExecutionStatus, RevisionVector
from app.domain.speech_runtime.contracts import (
    AudioReadinessState,
    SpeechPresentationCommand,
    SpeechPresentationMode,
    SpeechPresentationReport,
    SpeechPresentationReportStatus,
)
from app.domain.speech_runtime.runtime import SpeechRuntime
from tests.domain.speech_runtime.policy_fixtures import runtime_policy
from tests.domain.speech_runtime.test_presentation import _ready_candidate, _state

NOW = datetime(2026, 9, 12, tzinfo=timezone.utc)
PROVENANCE = ExecutionObservationProvenance(
    "decision", ("event",), RevisionVector(1, 1, 1), "trace"
)


async def presentation(
    audio: bool = False,
) -> tuple[SpeechRuntime, SpeechPresentationCommand, SpeechPresentationReport]:
    runtime = SpeechRuntime(runtime_policy(), clock=lambda: NOW)
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
    observation = await project_speech_execution_observation(runtime, command, started, PROVENANCE)
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
    projected = await project_speech_execution_observation(runtime, command, terminal, PROVENANCE)
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
    assert await project_speech_execution_observation(runtime, command, report, PROVENANCE) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mismatch", ["raw", "command", "asset", "candidate", "revision", "events", "decision"]
)
async def test_unaccepted_or_mismatched_input_rejected(mismatch: str) -> None:
    runtime, command, report = await presentation()
    if mismatch != "raw":
        await runtime.accept_report(report)
    provenance = PROVENANCE
    if mismatch == "command":
        command = replace(command, committed_at=NOW - timedelta(seconds=1))
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
    with pytest.raises(ValueError):
        await project_speech_execution_observation(runtime, command, report, provenance)


@pytest.mark.asyncio
async def test_missing_started_owner_time_rejected() -> None:
    runtime, command, report = await presentation()
    report = replace(report, started_at=None)
    await runtime.accept_report(report)
    with pytest.raises(ValueError):
        await project_speech_execution_observation(runtime, command, report, PROVENANCE)


@pytest.mark.asyncio
async def test_owner_fallback_timestamp_and_started_consistency() -> None:
    runtime, command, report = await presentation()
    await runtime.accept_report(report)
    terminal = replace(report, status=SpeechPresentationReportStatus.COMPLETED)
    candidate = await runtime.accept_report(terminal)
    projected = await project_speech_execution_observation(runtime, command, terminal, PROVENANCE)
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
        await project_speech_execution_observation(runtime, command, terminal, PROVENANCE)
