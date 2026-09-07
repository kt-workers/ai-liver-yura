from __future__ import annotations

from datetime import datetime, timezone

from app.domain.llm import LLMInterruptibility
from app.domain.speech_runtime.contracts import (
    AudioReadinessState,
    CandidateLifecycle,
    PreparedSpeechCandidate,
    SemanticVerificationRequirement,
    SpeechComponentReadiness,
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
from app.domain.speech_runtime.policy import SpeechCandidatePriority
from tests.domain.speech_runtime.policy_fixtures import runtime_policy


def _candidate(lifecycle: CandidateLifecycle) -> PreparedSpeechCandidate:
    now = datetime.now(timezone.utc)
    policy = runtime_policy()
    return PreparedSpeechCandidate(
        candidate_id="candidate",
        preparation_id="preparation",
        source_decision_id="decision",
        source_event_ids=("event",),
        speech_plan_id="plan",
        utterance_id="utterance",
        performance_plan_id="performance",
        source_context_revision=1,
        goal_revision=None,
        attention_revision=None,
        priority=SpeechCandidatePriority.FOREGROUND,
        interruptibility=LLMInterruptibility.INTERRUPTIBLE,
        expiry_policy_ref="expiry",
        runtime_policy_id=policy.policy_id,
        runtime_policy_revision=policy.policy_revision,
        required_preconditions=(),
        semantic_requirement=SemanticVerificationRequirement.REQUIRED,
        semantic_acceptance_id="acceptance",
        prepared_audio_ref="audio-current",
        presentation_modes=(SpeechPresentationMode.AUDIO_WITH_TEXT,),
        readiness=SpeechComponentReadiness(
            SpeechReadinessState.READY,
            SpeechReadinessState.READY,
            VerifierReadinessState.ACCEPTED,
            SpeechReadinessState.READY,
            AudioReadinessState.READY,
        ),
        lifecycle=lifecycle,
        created_at=now,
        updated_at=now,
        prepared_at=now,
    )


def _report(
    status: SpeechPresentationReportStatus, audio_ref: str = "audio-current"
) -> SpeechPresentationReport:
    now = datetime.now(timezone.utc)
    return SpeechPresentationReport(
        "presentation",
        "candidate",
        status,
        (SpeechPresentationMode.AUDIO_WITH_TEXT,),
        now if status is not SpeechPresentationReportStatus.FAILED_BEFORE_START else None,
        None,
        audio_ref,
        "timing-current",
    )


def test_only_trusted_presentation_reports_cross_execution_observation_boundary() -> None:
    assert (
        execution_observation_from_report(_report(SpeechPresentationReportStatus.STARTED))
        is not None
    )
    assert (
        execution_observation_from_report(_report(SpeechPresentationReportStatus.COMPLETED))
        is not None
    )
    assert (
        execution_observation_from_report(
            _report(SpeechPresentationReportStatus.FAILED_AFTER_START)
        )
        is not None
    )
    assert (
        execution_observation_from_report(_report(SpeechPresentationReportStatus.INTERRUPTED))
        is not None
    )
    assert (
        execution_observation_from_report(
            _report(SpeechPresentationReportStatus.FAILED_BEFORE_START)
        )
        is None
    )


def test_timing_requires_started_current_audio_and_exact_timing_identity() -> None:
    timing = SpeechTimingTrackReference("audio-current", "timing-current")
    assert not timing_publication_eligible(
        _candidate(CandidateLifecycle.PREPARED),
        _report(SpeechPresentationReportStatus.STARTED),
        timing,
    )
    assert timing_publication_eligible(
        _candidate(CandidateLifecycle.PRESENTING),
        _report(SpeechPresentationReportStatus.STARTED),
        timing,
    )
    assert not timing_publication_eligible(
        _candidate(CandidateLifecycle.PRESENTING),
        _report(SpeechPresentationReportStatus.STARTED, "stale-audio"),
        timing,
    )
    assert not timing_publication_eligible(
        _candidate(CandidateLifecycle.PRESENTING),
        _report(SpeechPresentationReportStatus.FAILED_BEFORE_START),
        timing,
    )
