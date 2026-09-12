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
from app.domain.contracts.common import JsonValue, require_identifier, utc_instant
from app.domain.speech_runtime.contracts import (
    AudioReadinessState,
    CandidateLifecycle,
    PreparedSpeechCandidate,
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
_TERMINALS = {
    SpeechPresentationReportStatus.COMPLETED: (
        CandidateLifecycle.COMPLETED,
        ExecutionStatus.COMPLETED,
    ),
    SpeechPresentationReportStatus.INTERRUPTED: (
        CandidateLifecycle.INTERRUPTED,
        ExecutionStatus.CANCELLED,
    ),
    SpeechPresentationReportStatus.FAILED_AFTER_START: (
        CandidateLifecycle.FAILED,
        ExecutionStatus.FAILED,
    ),
}


async def project_speech_execution_observation(
    runtime: SpeechRuntime,
    presentation_id: str,
    provenance: ExecutionObservationProvenance,
) -> TrustedExecutionObservation | None:
    """唯一のOwner snapshotから確定状態だけを投影し、timeoutやlifecycleを決定しない。"""
    require_identifier(presentation_id, "presentation_id")
    if not isinstance(provenance, ExecutionObservationProvenance):
        raise ValueError("exact integration provenanceが必要です")
    command, candidate, reports = await runtime.presentation_snapshot(presentation_id)
    if (
        not isinstance(command, SpeechPresentationCommand)
        or not isinstance(candidate, PreparedSpeechCandidate)
        or not isinstance(reports, tuple)
        or any(not isinstance(r, SpeechPresentationReport) for r in reports)
    ):
        raise ValueError("Presentation snapshotの型が不正です")
    shape = tuple(r.status for r in reports)
    if shape not in (
        (),
        (SpeechPresentationReportStatus.FAILED_BEFORE_START,),
        (SpeechPresentationReportStatus.STARTED,),
        *((SpeechPresentationReportStatus.STARTED, terminal) for terminal in _TERMINALS),
    ):
        raise ValueError("受理済みreport系列が閉じた契約に一致しません")
    discarded = (
        candidate.lifecycle in {CandidateLifecycle.CANCELLED, CandidateLifecycle.FAILED}
        and candidate.prepared_audio_ref is None
        and candidate.readiness.audio is AudioReadinessState.DISCARDED
    )
    if (
        command.presentation_id != presentation_id
        or candidate.candidate_id != command.candidate_id
        or candidate.utterance_id != command.utterance_id
        or (candidate.prepared_audio_ref != command.audio_ref and not discarded)
        or any(
            r.candidate_id != command.candidate_id
            or r.presentation_id != presentation_id
            or r.audio_ref != command.audio_ref
            or r.output_modes != command.modes
            for r in reports
        )
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
    if not reports:
        return None
    if shape == (SpeechPresentationReportStatus.FAILED_BEFORE_START,):
        if candidate.lifecycle is not CandidateLifecycle.FAILED:
            raise ValueError("開始前失敗reportとOwner lifecycleが一致しません")
        return None
    started = reports[0]
    if started.started_at is None:
        raise ValueError("Owner受理済みの提示開始時刻が必要です")
    if any(r.started_at != started.started_at for r in reports):
        raise ValueError("同一Presentationの提示開始時刻が一致しません")
    if utc_instant(candidate.updated_at) < utc_instant(started.started_at):
        raise ValueError("Ownerの現在時刻が提示開始より前です")
    if command.modes not in (
        (SpeechPresentationMode.TEXT_ONLY,),
        (SpeechPresentationMode.AUDIO_WITH_TEXT,),
    ):
        raise ValueError("閉じたPresentation modeに一致しません")
    if command.modes == (SpeechPresentationMode.AUDIO_WITH_TEXT,) and command.audio_ref is None:
        raise ValueError("音声提示には確定audio identityが必要です")
    if len(reports) == 2:
        terminal = reports[-1]
        expected_lifecycle, status = _TERMINALS[terminal.status]
        if candidate.lifecycle is not expected_lifecycle:
            raise ValueError("終端reportとOwner lifecycleが一致しません")
        code = terminal.status.value
        occurred = terminal.completed_at or candidate.updated_at
    elif candidate.lifecycle is CandidateLifecycle.PRESENTING:
        status = ExecutionStatus.OBSERVABLE
        code = SpeechPresentationReportStatus.STARTED.value
        occurred = started.started_at
    elif candidate.lifecycle in {CandidateLifecycle.FAILED, CandidateLifecycle.CANCELLED}:
        status, code = {
            CandidateLifecycle.FAILED: (
                ExecutionStatus.FAILED,
                "presentation_owner_failed_after_start",
            ),
            CandidateLifecycle.CANCELLED: (
                ExecutionStatus.CANCELLED,
                "presentation_owner_cancelled_after_start",
            ),
        }[candidate.lifecycle]
        occurred = candidate.updated_at
    else:
        raise ValueError("STARTED系列とOwner lifecycleを一意に投影できません")
    if utc_instant(occurred) > utc_instant(candidate.updated_at):
        raise ValueError("観測時刻がOwnerの現在時刻を超えています")
    effects: tuple[ObservedExecutionEffectEvidence, ...] = ()
    if status is ExecutionStatus.OBSERVABLE:
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
    # 自由文理由やfake terminal reportを作らず、Owner確定状態の固定分類だけを使う。
    details: JsonValue = {"code": code}
    return TrustedExecutionObservation(
        observation_identity(command.presentation_id, code),
        command.presentation_id,
        SPEECH_OBSERVATION_SOURCE,
        candidate.candidate_id,
        status,
        command.committed_at,
        started.started_at,
        occurred,
        provenance,
        details,
        effects,
    )
