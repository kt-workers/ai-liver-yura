"""受理済みSpeech Presentationを汎用観測へ機械的に投影する。"""

from __future__ import annotations

from app.domain.activity_execution.contracts import ExecutionEffectKind
from app.domain.activity_execution.observation import (
    ExecutionObservationIngressPolicy,
    ExecutionObservationProvenance,
    ExecutionObservationSourceBinding,
    ExecutionObservationSourceRule,
    ObservedExecutionEffectEvidence,
    TrustedExecutionObservation,
    observation_identity,
)
from app.domain.contracts import ExecutionStatus, RevisionVector
from app.domain.contracts.common import JsonValue, utc_instant
from app.domain.speech_runtime.contracts import (
    SpeechPresentationCommand,
    SpeechPresentationMode,
    SpeechPresentationReport,
    SpeechPresentationReportStatus,
)
from app.domain.speech_runtime.runtime import SpeechRuntime

SPEECH_OBSERVATION_SOURCE = ExecutionObservationSourceBinding("speech-presentation-report", 1)
SPEECH_OBSERVATION_RULE = ExecutionObservationSourceRule(
    SPEECH_OBSERVATION_SOURCE,
    (
        ExecutionStatus.OBSERVABLE,
        ExecutionStatus.COMPLETED,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.FAILED,
    ),
    ("text-presentation", "audio-presentation-started"),
    terminal_requires_prior_effect=True,
)
SPEECH_OBSERVATION_POLICY = ExecutionObservationIngressPolicy(
    "speech-execution-observation",
    1,
    (SPEECH_OBSERVATION_RULE,),
)
_STATUS = {
    SpeechPresentationReportStatus.STARTED: ExecutionStatus.OBSERVABLE,
    SpeechPresentationReportStatus.COMPLETED: ExecutionStatus.COMPLETED,
    SpeechPresentationReportStatus.INTERRUPTED: ExecutionStatus.CANCELLED,
    SpeechPresentationReportStatus.FAILED_AFTER_START: ExecutionStatus.FAILED,
}


async def project_speech_execution_observation(
    runtime: SpeechRuntime,
    command: SpeechPresentationCommand,
    report: SpeechPresentationReport,
    provenance: ExecutionObservationProvenance,
) -> TrustedExecutionObservation | None:
    """raw reportは受理しない。Ownerの確定時刻だけを使い、外部作用は実行しない。"""
    if not isinstance(command, SpeechPresentationCommand) or not isinstance(
        report, SpeechPresentationReport
    ):
        raise ValueError("型付きPresentation commandとreportが必要です")
    if not isinstance(provenance, ExecutionObservationProvenance):
        raise ValueError("exact integration provenanceが必要です")
    accepted_command, candidate, reports = await runtime.presentation_snapshot(
        command.presentation_id
    )
    if command != accepted_command or report not in reports:
        raise ValueError("Owner受理済みcommand/reportと一致しません")
    if (
        candidate.candidate_id != command.candidate_id
        or report.candidate_id != command.candidate_id
        or report.presentation_id != command.presentation_id
        or candidate.utterance_id != command.utterance_id
        or candidate.prepared_audio_ref != command.audio_ref
        or report.audio_ref != command.audio_ref
        or report.output_modes != command.modes
    ):
        raise ValueError("Presentationのcandidate/asset identityが一致しません")
    if (
        provenance.source_decision_id != candidate.source_decision_id
        or provenance.source_event_ids != candidate.source_event_ids
        or provenance.revisions
        != RevisionVector(
            candidate.source_context_revision, candidate.goal_revision, candidate.attention_revision
        )
    ):
        raise ValueError("Presentationとintegration provenanceが矛盾しています")
    if report.status is SpeechPresentationReportStatus.FAILED_BEFORE_START:
        return None
    started = reports[0]
    if started.status is not SpeechPresentationReportStatus.STARTED or started.started_at is None:
        raise ValueError("Owner受理済みの提示開始時刻が必要です")
    if report.started_at != started.started_at:
        raise ValueError("同一Presentationの提示開始時刻が一致しません")
    if command.modes not in (
        (SpeechPresentationMode.TEXT_ONLY,),
        (SpeechPresentationMode.AUDIO_WITH_TEXT,),
    ):
        raise ValueError("閉じたPresentation modeに一致しません")
    if command.modes == (SpeechPresentationMode.AUDIO_WITH_TEXT,) and command.audio_ref is None:
        raise ValueError("音声提示には確定audio identityが必要です")
    occurred = (
        report.started_at
        if report.status is SpeechPresentationReportStatus.STARTED
        else report.completed_at
    )
    if occurred is None:
        if reports[-1] != report:
            raise ValueError("対象reportのOwner確定時刻を取得できません")
        occurred = candidate.updated_at
    if utc_instant(occurred) > utc_instant(candidate.updated_at):
        raise ValueError("観測時刻がOwnerの現在時刻を超えています")
    effects: tuple[ObservedExecutionEffectEvidence, ...] = ()
    if report.status is SpeechPresentationReportStatus.STARTED:
        payload: dict[str, JsonValue] = {
            "presentation_id": command.presentation_id,
            "candidate_id": candidate.candidate_id,
            "utterance_id": command.utterance_id,
        }
        text = ObservedExecutionEffectEvidence(
            observation_identity(command.presentation_id, "text"),
            "text-presentation",
            candidate.candidate_id,
            ExecutionEffectKind.OBSERVABLE,
            payload,
        )
        effects = (text,)
        if command.modes == (SpeechPresentationMode.AUDIO_WITH_TEXT,):
            effects += (
                ObservedExecutionEffectEvidence(
                    observation_identity(command.presentation_id, "audio"),
                    "audio-presentation-started",
                    candidate.candidate_id,
                    ExecutionEffectKind.OBSERVABLE,
                    {**payload, "audio_ref": command.audio_ref},
                ),
            )
    # 自由文のfailure_code/interruption_reasonはコピーせず、確定statusの固定分類だけを使う。
    details: JsonValue = {"code": report.status.value}
    return TrustedExecutionObservation(
        observation_identity(command.presentation_id, report.status.value),
        command.presentation_id,
        SPEECH_OBSERVATION_SOURCE,
        candidate.candidate_id,
        _STATUS[report.status],
        command.committed_at,
        started.started_at,
        occurred,
        provenance,
        details,
        effects,
    )
