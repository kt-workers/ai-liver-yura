from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from app.domain.llm import LLMInterruptibility, LLMPriority
from app.domain.speech_runtime.admission import (
    SpeechPreparationAdmission,
    SpeechPreparationAdmissionPolicy,
)
from app.domain.speech_runtime.contracts import (
    AudioReadinessState,
    CandidateLifecycle,
    PreparedSpeechCandidate,
    SemanticVerificationRequirement,
    SpeechComponentReadiness,
    SpeechPresentationCapabilityView,
    SpeechPresentationCommand,
    SpeechPresentationCommitState,
    SpeechPresentationMode,
    SpeechPresentationReport,
    SpeechPresentationReportStatus,
    SpeechReadinessState,
    VerifierReadinessState,
)
from app.domain.speech_runtime.observation import (
    SpeechTimingTrackReference,
    execution_observation_from_report,
    timing_publication_eligible,
)
from app.domain.speech_runtime.orchestrator import SpeechPreparationOrchestrator
from app.domain.speech_runtime.presentation import SpeechPresentationExecutor
from app.domain.speech_runtime.runtime import SpeechRuntime
from app.domain.speech_runtime.tasks import CandidateTaskRegistry


def _ready_candidate() -> PreparedSpeechCandidate:
    now = datetime.now(timezone.utc)
    return PreparedSpeechCandidate(
        candidate_id="candidate",
        preparation_id="preparation",
        source_decision_id="decision",
        source_event_ids=("event",),
        speech_plan_id="plan",
        utterance_id="utterance",
        performance_plan_id="performance",
        source_context_revision=1,
        goal_revision=1,
        attention_revision=1,
        priority=LLMPriority.FOREGROUND,
        interruptibility=LLMInterruptibility.INTERRUPTIBLE,
        expiry_policy_ref="expiry",
        required_preconditions=("allowed",),
        semantic_requirement=SemanticVerificationRequirement.REQUIRED,
        semantic_acceptance_id="acceptance",
        prepared_audio_ref=None,
        presentation_modes=(SpeechPresentationMode.TEXT_ONLY,),
        readiness=SpeechComponentReadiness(
            SpeechReadinessState.READY,
            SpeechReadinessState.READY,
            VerifierReadinessState.ACCEPTED,
            SpeechReadinessState.READY,
            AudioReadinessState.NOT_REQUESTED,
        ),
        lifecycle=CandidateLifecycle.READY_TO_PRESENT,
        created_at=now,
        updated_at=now,
    )


def _state() -> SpeechPresentationCommitState:
    return SpeechPresentationCommitState(
        source_context_revision=1,
        goal_revision=1,
        attention_revision=1,
        turn_id="turn",
        response_obligation_id=None,
        satisfied_preconditions=("allowed",),
        capability=SpeechPresentationCapabilityView("capability", 1, True, False, True, False),
        expression_revision=None,
        observed_at=datetime.now(timezone.utc),
        semantic_acceptance_id="acceptance",
        performance_plan_id="performance",
    )


@pytest.mark.asyncio
async def test_presentation_adapter_runs_after_commit_without_blocking_next_preparation() -> None:
    runtime, tasks = SpeechRuntime(), CandidateTaskRegistry()
    await runtime.register(_ready_candidate())
    started, release, next_preparation = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def adapter(
        command: SpeechPresentationCommand,
    ) -> AsyncIterator[SpeechPresentationReport]:
        started.set()
        now = datetime.now(timezone.utc)
        yield SpeechPresentationReport(
            presentation_id="presentation",
            candidate_id="candidate",
            status=SpeechPresentationReportStatus.STARTED,
            output_modes=(SpeechPresentationMode.TEXT_ONLY,),
            started_at=now,
            completed_at=None,
            audio_ref=None,
            timing_ref=None,
        )
        await release.wait()
        assert command.candidate_id == "candidate"
        now = datetime.now(timezone.utc)
        yield SpeechPresentationReport(
            presentation_id="presentation",
            candidate_id="candidate",
            status=SpeechPresentationReportStatus.COMPLETED,
            output_modes=(SpeechPresentationMode.TEXT_ONLY,),
            started_at=now,
            completed_at=now,
            audio_ref=None,
            timing_ref=None,
        )

    command = await SpeechPresentationExecutor(runtime, tasks).commit_and_present(
        candidate_id="candidate",
        state=_state(),
        presentation_id="presentation",
        adapter=adapter,
    )
    await started.wait()
    next_preparation.set()
    assert next_preparation.is_set()
    assert command.candidate_id == "candidate"
    assert (await runtime.candidate("candidate")).lifecycle is CandidateLifecycle.PRESENTING
    release.set()
    while tasks.pending_task_count:
        await asyncio.sleep(0)
    assert (await runtime.candidate("candidate")).lifecycle is CandidateLifecycle.COMPLETED


@pytest.mark.asyncio
async def test_report_identity_mismatch_is_rejected() -> None:
    runtime = SpeechRuntime()
    await runtime.register(_ready_candidate())
    await runtime.commit("candidate", _state(), "presentation")
    now = datetime.now(timezone.utc)
    report = SpeechPresentationReport(
        presentation_id="wrong-presentation",
        candidate_id="candidate",
        status=SpeechPresentationReportStatus.FAILED_BEFORE_START,
        output_modes=(SpeechPresentationMode.TEXT_ONLY,),
        started_at=None,
        completed_at=now,
        audio_ref=None,
        timing_ref=None,
    )
    with pytest.raises(ValueError, match="identity"):
        await runtime.accept_report(report)
    assert (await runtime.candidate("candidate")).lifecycle is CandidateLifecycle.PRESENTING


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "started", "expected"),
    [
        (SpeechPresentationReportStatus.FAILED_BEFORE_START, False, CandidateLifecycle.FAILED),
        (SpeechPresentationReportStatus.FAILED_AFTER_START, True, CandidateLifecycle.FAILED),
        (SpeechPresentationReportStatus.INTERRUPTED, True, CandidateLifecycle.INTERRUPTED),
    ],
)
async def test_terminal_presentation_reports_are_truthful(
    status: SpeechPresentationReportStatus, started: bool, expected: CandidateLifecycle
) -> None:
    runtime = SpeechRuntime()
    await runtime.register(_ready_candidate())
    await runtime.commit("candidate", _state(), "presentation")
    now = datetime.now(timezone.utc)
    if started:
        await runtime.accept_report(
            SpeechPresentationReport(
                "presentation",
                "candidate",
                SpeechPresentationReportStatus.STARTED,
                (SpeechPresentationMode.TEXT_ONLY,),
                now,
                None,
                None,
                None,
            )
        )
    report = SpeechPresentationReport(
        presentation_id="presentation",
        candidate_id="candidate",
        status=status,
        output_modes=(SpeechPresentationMode.TEXT_ONLY,),
        started_at=now if started else None,
        completed_at=now,
        audio_ref=None,
        timing_ref=None,
    )
    updated = await runtime.accept_report(report)
    assert updated.lifecycle is expected
    assert (await runtime.presentation_reports("presentation"))[-1] == report


@pytest.mark.asyncio
async def test_started_then_completed_and_contradictory_late_report_is_rejected() -> None:
    runtime = SpeechRuntime()
    await runtime.register(_ready_candidate())
    await runtime.commit("candidate", _state(), "presentation")
    now = datetime.now(timezone.utc)
    started = SpeechPresentationReport(
        "presentation",
        "candidate",
        SpeechPresentationReportStatus.STARTED,
        (SpeechPresentationMode.TEXT_ONLY,),
        now,
        None,
        None,
        None,
    )
    await runtime.accept_report(started)
    completed = SpeechPresentationReport(
        "presentation",
        "candidate",
        SpeechPresentationReportStatus.COMPLETED,
        (SpeechPresentationMode.TEXT_ONLY,),
        now,
        now,
        None,
        None,
    )
    await runtime.accept_report(completed)
    with pytest.raises(ValueError):
        await runtime.accept_report(started)
    assert (await runtime.candidate("candidate")).lifecycle is CandidateLifecycle.COMPLETED


@pytest.mark.asyncio
async def test_playback_wait_does_not_block_next_candidate_preparation_or_heartbeat() -> None:
    runtime, tasks = SpeechRuntime(), CandidateTaskRegistry()
    await runtime.register(_ready_candidate())
    playback_started, release_playback = asyncio.Event(), asyncio.Event()
    verifier_done, performance_done, heartbeat = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def adapter(_: SpeechPresentationCommand) -> AsyncIterator[SpeechPresentationReport]:
        playback_started.set()
        now = datetime.now(timezone.utc)
        yield SpeechPresentationReport(
            "presentation",
            "candidate",
            SpeechPresentationReportStatus.STARTED,
            (SpeechPresentationMode.TEXT_ONLY,),
            now,
            None,
            None,
            None,
        )
        await release_playback.wait()
        now = datetime.now(timezone.utc)
        yield SpeechPresentationReport(
            "presentation",
            "candidate",
            SpeechPresentationReportStatus.COMPLETED,
            (SpeechPresentationMode.TEXT_ONLY,),
            now,
            now,
            None,
            None,
        )

    await SpeechPresentationExecutor(runtime, tasks).commit_and_present(
        candidate_id="candidate", state=_state(), presentation_id="presentation", adapter=adapter
    )
    await playback_started.wait()

    async def verifier() -> object:
        verifier_done.set()
        return object()

    async def performance() -> object:
        performance_done.set()
        return object()

    async def unrelated() -> None:
        heartbeat.set()

    orchestrator = SpeechPreparationOrchestrator(
        tasks, SpeechPreparationAdmission(SpeechPreparationAdmissionPolicy(2, 2, 4))
    )

    async def character() -> object:
        return object()

    character_task = orchestrator.start_preparation(
        "candidate-b", 1, LLMPriority.FOREGROUND, character
    )
    assert character_task is not None
    await character_task
    orchestrator.fan_out_after_character(
        "candidate-b", 1, verifier, performance
    )
    await unrelated()
    await verifier_done.wait()
    await performance_done.wait()
    assert heartbeat.is_set()
    assert (await runtime.candidate("candidate")).lifecycle is CandidateLifecycle.PRESENTING
    release_playback.set()
    orchestrator.complete_preparation("candidate-b", 1)
    while tasks.pending_task_count:
        await asyncio.sleep(0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state",
    [
        replace(_state(), source_context_revision=2),
        replace(_state(), goal_revision=2),
        replace(_state(), attention_revision=2),
        replace(_state(), semantic_acceptance_id="other-acceptance"),
        replace(_state(), performance_plan_id="other-performance"),
    ],
)
async def test_commit_rejects_stale_or_identity_mismatched_live_state(
    state: SpeechPresentationCommitState,
) -> None:
    runtime = SpeechRuntime()
    await runtime.register(_ready_candidate())
    with pytest.raises(ValueError, match="revalidation"):
        await runtime.commit("candidate", state, "presentation")


@pytest.mark.asyncio
async def test_commit_rejects_turn_focus_and_audio_identity_mismatch() -> None:
    runtime = SpeechRuntime()
    await runtime.register(replace(_ready_candidate(), turn_id="expected-turn", focus_revision=1))
    with pytest.raises(ValueError, match="revalidation"):
        await runtime.commit("candidate", replace(_state(), turn_id="other-turn"), "presentation")
    runtime = SpeechRuntime()
    await runtime.register(
        replace(
            _ready_candidate(),
            prepared_audio_ref="audio-current",
            presentation_modes=(SpeechPresentationMode.AUDIO_WITH_TEXT,),
        )
    )
    with pytest.raises(ValueError, match="revalidation"):
        await runtime.commit(
            "candidate",
            replace(
                _state(),
                capability=SpeechPresentationCapabilityView(
                    "capability", 1, True, True, True, False
                ),
                prepared_audio_ref="stale-audio",
            ),
            "presentation",
        )


@pytest.mark.asyncio
async def test_tts_degradation_can_truthfully_fall_back_to_text_only() -> None:
    runtime = SpeechRuntime()
    await runtime.register(_ready_candidate())
    command = await runtime.commit("candidate", _state(), "presentation")
    assert command.modes == (SpeechPresentationMode.TEXT_ONLY,)
    assert command.audio_ref is None


@pytest.mark.asyncio
async def test_audio_required_policy_fails_closed_when_audio_is_unavailable() -> None:
    runtime = SpeechRuntime()
    await runtime.register(
        replace(
            _ready_candidate(),
            presentation_modes=(SpeechPresentationMode.AUDIO_WITH_TEXT,),
            readiness=SpeechComponentReadiness(
                SpeechReadinessState.READY,
                SpeechReadinessState.READY,
                VerifierReadinessState.ACCEPTED,
                SpeechReadinessState.READY,
                AudioReadinessState.FAILED,
            ),
        )
    )
    with pytest.raises(ValueError, match="mode"):
        await runtime.commit("candidate", _state(), "presentation")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("terminal", "expected"),
    [
        (SpeechPresentationReportStatus.COMPLETED, CandidateLifecycle.COMPLETED),
        (SpeechPresentationReportStatus.FAILED_AFTER_START, CandidateLifecycle.FAILED),
        (SpeechPresentationReportStatus.INTERRUPTED, CandidateLifecycle.INTERRUPTED),
    ],
)
async def test_executor_stream_accepts_started_before_terminal_and_preserves_effect(
    terminal: SpeechPresentationReportStatus, expected: CandidateLifecycle
) -> None:
    runtime, tasks = SpeechRuntime(), CandidateTaskRegistry()
    candidate = replace(
        _ready_candidate(),
        prepared_audio_ref="audio",
        presentation_modes=(SpeechPresentationMode.AUDIO_WITH_TEXT,),
    )
    await runtime.register(candidate)
    state = replace(
        _state(),
        capability=SpeechPresentationCapabilityView("capability", 1, True, True, True, True),
        prepared_audio_ref="audio",
    )
    emitted, release = asyncio.Event(), asyncio.Event()

    async def adapter(_: SpeechPresentationCommand) -> AsyncIterator[SpeechPresentationReport]:
        now = datetime.now(timezone.utc)
        emitted.set()
        yield SpeechPresentationReport(
            "presentation",
            "candidate",
            SpeechPresentationReportStatus.STARTED,
            (SpeechPresentationMode.AUDIO_WITH_TEXT,),
            now,
            None,
            "audio",
            "timing",
        )
        await release.wait()
        yield SpeechPresentationReport(
            "presentation",
            "candidate",
            terminal,
            (SpeechPresentationMode.AUDIO_WITH_TEXT,),
            now,
            now,
            "audio",
            "timing",
        )

    await SpeechPresentationExecutor(runtime, tasks).commit_and_present(
        candidate_id="candidate", state=state, presentation_id="presentation", adapter=adapter
    )
    await emitted.wait()
    await asyncio.sleep(0)
    current = await runtime.candidate("candidate")
    history = await runtime.presentation_reports("presentation")
    assert current.lifecycle is CandidateLifecycle.PRESENTING
    assert history[0].status is SpeechPresentationReportStatus.STARTED
    assert timing_publication_eligible(
        current, history[0], SpeechTimingTrackReference("audio", "timing")
    )
    assert execution_observation_from_report(history[0]) is not None
    assert tasks.pending_task_count == 1
    release.set()
    while tasks.pending_task_count:
        await asyncio.sleep(0)
    assert (await runtime.candidate("candidate")).lifecycle is expected
    assert len(await runtime.presentation_reports("presentation")) == 2


@pytest.mark.asyncio
async def test_started_only_stream_fails_closed_instead_of_stranding_presentation() -> None:
    runtime, tasks = SpeechRuntime(), CandidateTaskRegistry()
    await runtime.register(_ready_candidate())

    async def adapter(_: SpeechPresentationCommand) -> AsyncIterator[SpeechPresentationReport]:
        now = datetime.now(timezone.utc)
        yield SpeechPresentationReport(
            "presentation",
            "candidate",
            SpeechPresentationReportStatus.STARTED,
            (SpeechPresentationMode.TEXT_ONLY,),
            now,
            None,
            None,
            None,
        )

    await SpeechPresentationExecutor(runtime, tasks).commit_and_present(
        candidate_id="candidate", state=_state(), presentation_id="presentation", adapter=adapter
    )
    while tasks.pending_task_count:
        await asyncio.sleep(0)
    assert (await runtime.candidate("candidate")).lifecycle is CandidateLifecycle.FAILED


@pytest.mark.asyncio
async def test_verifier_rejection_never_allows_speculative_artifact_presentation() -> None:
    runtime = SpeechRuntime()
    await runtime.register(
        replace(
            _ready_candidate(),
            lifecycle=CandidateLifecycle.REJECTED,
            prepared_audio_ref="speculative-audio",
        )
    )
    with pytest.raises(ValueError, match="terminal"):
        await runtime.commit("candidate", _state(), "presentation")
