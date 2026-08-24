from __future__ import annotations

from dataclasses import dataclass

from .contracts import (
    CandidateLifecycle,
    PreparedSpeechCandidate,
    SpeechPresentationReport,
    SpeechPresentationReportStatus,
)


@dataclass(frozen=True, slots=True)
class TrustedSpeechExecutionObservation:
    """#329へ渡せるのはPresentationのtrusted reportだけである。"""

    report: SpeechPresentationReport

    def __post_init__(self) -> None:
        if self.report.status is SpeechPresentationReportStatus.FAILED_BEFORE_START:
            raise ValueError("external effectのないreportはexecution observationではありません")


@dataclass(frozen=True, slots=True)
class SpeechTimingTrackReference:
    """#340へ渡す前の既存timing trackのidentity照合だけを担う。"""

    audio_ref: str
    timing_ref: str

    def __post_init__(self) -> None:
        if not self.audio_ref or not self.timing_ref:
            raise ValueError("timing track identity が不正です")


def execution_observation_from_report(
    report: SpeechPresentationReport,
) -> TrustedSpeechExecutionObservation | None:
    if report.status is SpeechPresentationReportStatus.FAILED_BEFORE_START:
        return None
    return TrustedSpeechExecutionObservation(report)


def timing_publication_eligible(
    candidate: PreparedSpeechCandidate,
    report: SpeechPresentationReport,
    timing: SpeechTimingTrackReference,
) -> bool:
    """STARTED済みでcurrent audioとexact一致するtimingだけを#340境界へ通す。"""
    return (
        candidate.lifecycle is CandidateLifecycle.PRESENTING
        and report.status is SpeechPresentationReportStatus.STARTED
        and report.started_at is not None
        and candidate.prepared_audio_ref is not None
        and candidate.prepared_audio_ref == report.audio_ref == timing.audio_ref
        and report.timing_ref == timing.timing_ref
    )
