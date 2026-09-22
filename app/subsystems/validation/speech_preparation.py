"""生成と意味検証の確定結果を本番の候補準備状態へ引き渡す。"""

from collections.abc import Awaitable
from dataclasses import dataclass, replace
from typing import Protocol

from app.domain.character_language import CharacterLanguageContextSnapshot, CharacterUtterance
from app.domain.contracts.common import JsonValue
from app.domain.semantic_verification import SemanticAcceptance, SemanticAcceptanceState
from app.domain.speech_performance import SpeechPerformancePlan
from app.domain.speech_runtime.contracts import (
    AudioReadinessState,
    CandidateLifecycle,
    PreparedSpeechCandidate,
    SemanticVerificationRequirement,
    SpeechComponentReadiness,
    SpeechPresentationCommitState,
    SpeechPresentationMode,
    SpeechReadinessState,
    TTSPreparationMode,
    VerifierReadinessState,
)
from app.domain.speech_runtime.discard import (
    PreparedAudioDiscarder,
    PreparedAudioDiscardReason,
    PreparedAudioDiscardRequest,
)
from app.domain.speech_runtime.policy import SpeechCandidatePriority, SpeechRuntimeOperationalPolicy
from app.domain.speech_runtime.presentation import PresentationAdapter
from app.domain.speech_runtime.queue import PreparedSpeechQueue, PreparedSpeechQueueCoordinator
from app.domain.speech_runtime.runtime import SpeechRuntime

from .audio_presentation import LabAudioResources
from .body import _project
from .contracts import Gate, RunStatus, TargetObservation, ValidationFixture
from .generated_audio import GeneratedAudioBindings, GeneratedAudioSettings
from .runtime import RunContext
from .speculative_audio import prepare_pending_audio
from .speech_presentation import execute_presentation
from .speech_session import SpeechPreparationSession
from .tts import TTSSynthesisCase, synthesis_run_status, synthesize_audio
from .tts import _project as project_tts


@dataclass(frozen=True)
class SpeechPreparationSettings:
    policy: SpeechRuntimeOperationalPolicy
    priority: SpeechCandidatePriority
    expiry_policy_ref: str
    required_preconditions: tuple[str, ...]
    presentation_modes: tuple[SpeechPresentationMode, ...]
    queue_for_revalidation: bool = False
    validate_for_presentation: bool = False
    present_after_validation: bool = False
    audio: GeneratedAudioSettings | None = None
    tts_mode: TTSPreparationMode = TTSPreparationMode.AFTER_SEMANTIC_ACCEPTANCE

    def __post_init__(self) -> None:
        if not isinstance(self.tts_mode, TTSPreparationMode):
            raise ValueError("音声合成の開始方式が不正です")
        if self.audio is not None and self.tts_mode is TTSPreparationMode.DISABLED:
            raise ValueError("合成を無効にするときは音声合成設定を渡せません")
        if type(self.present_after_validation) is not bool or (
            self.present_after_validation and not self.validate_for_presentation
        ):
            raise ValueError("提示への継続には現在状態の再照合が必要です")
        if self.validate_for_presentation and not self.queue_for_revalidation:
            raise ValueError("提示前照合には待ち行列への移行が必要です")
        if (
            type(self.validate_for_presentation) is not bool
            or type(self.queue_for_revalidation) is not bool
        ):
            raise ValueError("再照合への移行指定が不正です")
        object.__setattr__(self, "required_preconditions", tuple(self.required_preconditions))
        object.__setattr__(self, "presentation_modes", tuple(self.presentation_modes))

    def typed_inputs(self) -> JsonValue:
        return _project(
            {
                "policy": self.policy,
                "priority": self.priority,
                "expiry_policy_ref": self.expiry_policy_ref,
                "required_preconditions": self.required_preconditions,
                "presentation_modes": self.presentation_modes,
                "queue_for_revalidation": self.queue_for_revalidation,
                "validate_for_presentation": self.validate_for_presentation,
                "present_after_validation": self.present_after_validation,
                "tts_mode": self.tts_mode,
                "audio": self.audio.typed_inputs() if self.audio is not None else None,
            }
        )


class SpeechRevalidationStatePort(Protocol):
    async def current_state(
        self, candidate: PreparedSpeechCandidate
    ) -> SpeechPresentationCommitState: ...


class _NoPreparedAudio:
    async def discard(self, request: PreparedAudioDiscardRequest) -> None:
        raise ValueError("音声合成前の候補に準備済み音声は存在しません")


async def prepare_generated_speech(
    context: RunContext,
    settings: SpeechPreparationSettings,
    snapshot: CharacterLanguageContextSnapshot,
    utterance: CharacterUtterance,
    performance: SpeechPerformancePlan,
    acceptance: SemanticAcceptance | Awaitable[SemanticAcceptance],
    revalidation: SpeechRevalidationStatePort | None = None,
    presentation: PresentationAdapter | None = None,
    audio: GeneratedAudioBindings | None = None,
    fixture: ValidationFixture | None = None,
    session: SpeechPreparationSession | None = None,
) -> TargetObservation:
    if (
        performance.utterance_id != utterance.utterance_id
        or settings.priority.llm_priority != snapshot.llm_priority
    ):
        raise ValueError("候補準備へ渡す生成結果または優先順位が一致しません")
    if settings.audio is not None and (audio is None or fixture is None):
        raise ValueError("音声合成への接続と入力条件が必要です")
    if settings.present_after_validation and presentation is None and audio is None:
        raise ValueError("提示への継続には提示先の接続が必要です")
    if settings.queue_for_revalidation and revalidation is None:
        raise ValueError("再照合には最新状態を取得する接続が必要です")
    now = max(performance.created_at, utterance.committed_at)
    if isinstance(acceptance, SemanticAcceptance):
        now = max(now, acceptance.committed_at)
    resources: LabAudioResources | None
    if session is not None:
        session.observe(context, settings.policy, now)
        runtime, resources = session.runtime, session.resources
    else:
        runtime = SpeechRuntime(settings.policy, lambda: now)

        resources = LabAudioResources() if settings.audio is not None else None

        async def close() -> None:
            try:
                if resources is not None:
                    discarder = PreparedAudioDiscarder(runtime, resources)
                    for candidate_id in await runtime.active_candidate_ids():
                        await discarder.discard_current(
                            candidate_id,
                            runtime.generation(candidate_id),
                            PreparedAudioDiscardReason.CANDIDATE_CANCELLED,
                        )
                await runtime.shutdown()
            finally:
                if resources is not None:
                    await resources.close()

        context.add_cleanup("speech.generated_preparation", close)
    prefix = snapshot.request_id
    revisions = snapshot.revisions
    candidate = PreparedSpeechCandidate(
        candidate_id=f"{prefix}:candidate",
        preparation_id=f"{prefix}:preparation",
        source_decision_id=utterance.candidate.source_decision_id,
        source_event_ids=utterance.candidate.source_event_ids,
        speech_plan_id=snapshot.semantic_plan.plan_id,
        utterance_id=None,
        performance_plan_id=None,
        source_context_revision=revisions.source_context_revision,
        goal_revision=revisions.goal_revision,
        attention_revision=revisions.attention_revision,
        priority=settings.priority,
        interruptibility=snapshot.interruptibility,
        expiry_policy_ref=settings.expiry_policy_ref,
        runtime_policy_id=settings.policy.policy_id,
        runtime_policy_revision=settings.policy.policy_revision,
        required_preconditions=settings.required_preconditions,
        semantic_requirement=SemanticVerificationRequirement.REQUIRED,
        semantic_acceptance_id=None,
        prepared_audio_ref=None,
        presentation_modes=settings.presentation_modes,
        readiness=SpeechComponentReadiness(
            SpeechReadinessState.READY,
            SpeechReadinessState.PENDING,
            VerifierReadinessState.PENDING,
            SpeechReadinessState.PENDING,
            AudioReadinessState.NOT_REQUESTED,
        ),
        lifecycle=CandidateLifecycle.PREPARING,
        created_at=snapshot.captured_at,
        updated_at=now,
    )
    await context.invoke_product("speech.preparation_register", lambda: runtime.register(candidate))
    scheduling: JsonValue = None
    pending_synthesis = None
    if not isinstance(acceptance, SemanticAcceptance):
        if settings.audio is None or audio is None or fixture is None or resources is None:
            raise ValueError("採用待ち中の音声準備には合成設定と接続が必要です")
        acceptance, pending_synthesis, scheduling = await prepare_pending_audio(
            context,
            runtime,
            resources,
            settings.policy,
            settings.priority,
            settings.tts_mode,
            candidate,
            utterance,
            performance,
            acceptance,
            settings.audio,
            audio,
            fixture,
            session,
        )
    if (
        acceptance.semantic_plan_id != snapshot.semantic_plan.plan_id
        or acceptance.utterance_id != utterance.utterance_id
    ):
        raise ValueError("候補準備へ渡す採用結果の識別子が一致しません")
    now = max(now, acceptance.committed_at)
    if pending_synthesis is not None:
        now = max(now, pending_synthesis.completed_at)
    if session is not None:
        session.observe(context, settings.policy, now)
    current_audio = (await runtime.candidate(candidate.candidate_id)).readiness.audio
    readiness = SpeechComponentReadiness(
        SpeechReadinessState.READY,
        SpeechReadinessState.READY,
        VerifierReadinessState.ACCEPTED
        if acceptance.state is SemanticAcceptanceState.ACCEPTED
        else VerifierReadinessState.REJECTED,
        SpeechReadinessState.READY,
        current_audio,
    )
    prepared = await context.invoke_product(
        "speech.preparation_commit",
        lambda: runtime.commit_generation_result(
            candidate.candidate_id,
            runtime.generation(candidate.candidate_id),
            readiness=readiness,
            utterance_id=utterance.utterance_id,
            performance_plan_id=performance.performance_plan_id,
            semantic_acceptance_id=acceptance.acceptance_id,
        ),
    )
    synthesized: JsonValue = (
        project_tts(pending_synthesis) if pending_synthesis is not None else None
    )
    if pending_synthesis is not None:
        if (
            pending_synthesis.artifact is None
            and acceptance.state is SemanticAcceptanceState.ACCEPTED
        ):
            return _evidence(
                {"candidate": prepared, "synthesis": synthesized, "scheduling": scheduling},
                synthesis_run_status(pending_synthesis),
            )
        assert audio is not None and resources is not None
        presentation = audio.presentation(resources)
    if (
        prepared is not None
        and prepared.lifecycle is CandidateLifecycle.PREPARED
        and settings.audio is not None
        and pending_synthesis is None
        and scheduling is None
    ):
        assert audio is not None and fixture is not None and resources is not None
        request = settings.audio.request(candidate.candidate_id, utterance, performance, now)
        synthesis_case = TTSSynthesisCase(
            fixture,
            request,
            settings.audio.mapping,
            settings.audio.operational,
            settings.audio.retry,
        )
        _, synthesis = await synthesize_audio(
            context, synthesis_case, audio.client, resources, preserve_identity=True
        )
        synthesized = project_tts(synthesis)
        now = max(now, synthesis.completed_at)
        if session is not None:
            session.observe(context, settings.policy, now)
        if synthesis.artifact is None:
            return _evidence(
                {"candidate": prepared, "synthesis": synthesized}, synthesis_run_status(synthesis)
            )
        prepared = await context.invoke_product(
            "speech.audio_commit",
            lambda: runtime.commit_generation_result(
                candidate.candidate_id,
                runtime.generation(candidate.candidate_id),
                readiness=replace(readiness, audio=AudioReadinessState.READY),
                prepared_audio_ref=synthesis.artifact.audio_ref
                if synthesis.artifact is not None
                else None,
            ),
        )
        presentation = audio.presentation(resources)
    if (
        not settings.queue_for_revalidation
        or prepared is None
        or prepared.lifecycle is not CandidateLifecycle.PREPARED
    ):
        return _evidence(
            {"candidate": prepared, "synthesis": synthesized, "scheduling": scheduling}
            if scheduling is not None
            else prepared
        )
    queue = (
        session.queue
        if session is not None
        else PreparedSpeechQueueCoordinator(
            runtime,
            PreparedSpeechQueue(settings.policy),
            PreparedAudioDiscarder(
                runtime, resources if resources is not None else _NoPreparedAudio()
            ),
        )
    )

    async def close_queue() -> None:
        queue.shutdown()

    context.add_cleanup("speech.prepared_queue", close_queue)
    admission = await context.invoke_product(
        "speech.queue_admission",
        lambda: queue.enqueue_current(
            prepared.candidate_id, runtime.generation(prepared.candidate_id)
        ),
    )
    current = await context.invoke_product("speech.queue_take", queue.pop_for_revalidation)
    if not admission.admitted or current is None:
        return _evidence(
            {
                "candidate": await runtime.candidate(prepared.candidate_id),
                "queue_admission": admission,
                "revalidation_state": None,
            }
        )
    revalidating = current
    assert revalidation is not None
    state = await context.invoke_port(
        "speech.revalidation_state", lambda: revalidation.current_state(revalidating)
    )
    if not isinstance(state, SpeechPresentationCommitState):
        raise ValueError("提示前の最新状態は製品の型付き契約でなければなりません")
    if settings.validate_for_presentation:
        validated = await context.invoke_product(
            "speech.revalidation_commit",
            lambda: runtime.revalidate_current(
                revalidating.candidate_id, runtime.generation(revalidating.candidate_id), state
            ),
        )
        if validated is None:
            raise ValueError("再照合中に候補の世代が変わりました")
        current = validated
    presented: JsonValue = None
    if settings.present_after_validation:
        assert presentation is not None
        result = await execute_presentation(
            context, runtime, current, state, presentation, f"{prefix}:presentation"
        )
        presented = result.typed_outputs
        current = await runtime.candidate(current.candidate_id)
    return _evidence(
        {
            "candidate": current,
            "queue_admission": admission,
            "revalidation_state": state,
            "presentation": presented,
            "synthesis": synthesized,
            "scheduling": scheduling,
        }
    )


def _evidence(value: object, status: RunStatus = RunStatus.COMPLETED) -> TargetObservation:
    return TargetObservation(status, Gate.NOT_RUN, _project(value))
