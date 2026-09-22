"""採用待ちの候補へ本番の先行合成制御と音声破棄を接続する。"""

import asyncio
from collections.abc import Awaitable
from dataclasses import replace

from app.adapters.tts import TTSSynthesisResult
from app.domain.character_language import CharacterUtterance
from app.domain.contracts.common import JsonValue
from app.domain.semantic_verification import SemanticAcceptance, SemanticAcceptanceState
from app.domain.speech_performance import SpeechPerformancePlan
from app.domain.speech_runtime.admission import SpeechPreparationAdmission
from app.domain.speech_runtime.contracts import (
    AudioReadinessState,
    PreparedSpeechCandidate,
    SpeechReadinessState,
    TTSPreparationMode,
)
from app.domain.speech_runtime.discard import PreparedAudioDiscarder, PreparedAudioDiscardReason
from app.domain.speech_runtime.orchestrator import SpeechPreparationOrchestrator
from app.domain.speech_runtime.policy import SpeechCandidatePriority, SpeechRuntimeOperationalPolicy
from app.domain.speech_runtime.runtime import SpeechRuntime
from app.domain.speech_runtime.tasks import CandidateTaskRegistry

from .audio_presentation import LabAudioResources
from .body import _project
from .contracts import ValidationFixture
from .generated_audio import GeneratedAudioBindings, GeneratedAudioSettings
from .runtime import RunContext
from .speech_session import SpeechPreparationSession
from .tts import TTSSynthesisCase, synthesize_audio


async def prepare_pending_audio(
    context: RunContext,
    runtime: SpeechRuntime,
    resources: LabAudioResources,
    policy: SpeechRuntimeOperationalPolicy,
    priority: SpeechCandidatePriority,
    mode: TTSPreparationMode,
    candidate: PreparedSpeechCandidate,
    utterance: CharacterUtterance,
    performance: SpeechPerformancePlan,
    pending_acceptance: Awaitable[SemanticAcceptance],
    settings: GeneratedAudioSettings,
    bindings: GeneratedAudioBindings,
    fixture: ValidationFixture,
    session: SpeechPreparationSession | None = None,
) -> tuple[SemanticAcceptance, TTSSynthesisResult | None, JsonValue]:
    """一反復の同一候補・資源表を維持する。全体の複数候補負荷試験は別に行う。"""
    tasks = CandidateTaskRegistry() if session is None else session.tasks
    admission = SpeechPreparationAdmission(policy) if session is None else session.admission
    owner = SpeechPreparationOrchestrator(tasks, admission) if session is None else session.owner
    candidate_id = candidate.candidate_id
    generation = runtime.generation(candidate_id)
    result: TTSSynthesisResult | None = None
    peak = 0
    before_acceptance: PreparedSpeechCandidate | None = None
    discarder = PreparedAudioDiscarder(runtime, resources)

    async def character_completed() -> object:
        # 生成済み発話の引継ぎ。ここで人物表現を再生成しない。
        return utterance

    async def synthesize() -> object:
        nonlocal result
        current = await runtime.candidate(candidate_id)
        pending = replace(
            current.readiness,
            character=SpeechReadinessState.READY,
            performance=SpeechReadinessState.READY,
            audio=AudioReadinessState.PENDING,
        )
        await runtime.commit_generation_result(
            candidate_id,
            generation,
            readiness=pending,
            utterance_id=utterance.utterance_id,
            performance_plan_id=performance.performance_plan_id,
        )
        request = settings.request(
            candidate_id,
            utterance,
            performance,
            max(utterance.committed_at, performance.created_at),
        )
        _, result = await synthesize_audio(
            context,
            TTSSynthesisCase(
                fixture, request, settings.mapping, settings.operational, settings.retry
            ),
            bindings.client,
            resources,
            preserve_identity=True,
        )
        current = await runtime.candidate(candidate_id)
        await runtime.commit_generation_result(
            candidate_id,
            generation,
            readiness=replace(
                current.readiness,
                audio=AudioReadinessState.READY
                if result.artifact is not None
                else AudioReadinessState.FAILED,
            ),
            prepared_audio_ref=result.artifact.audio_ref if result.artifact is not None else None,
        )
        return result

    synthesis_task: asyncio.Task[object] | None = None
    synthesis_failed = False
    try:
        admitted = owner.start_preparation(candidate_id, generation, priority, character_completed)
        if admitted is None:
            raise ValueError("先行合成の準備枠を取得できません")
        await admitted
        # 既に確定している採否を確認し、不採用候補へ合成を予約しない。
        resolved = (
            pending_acceptance.result()
            if isinstance(pending_acceptance, asyncio.Future) and pending_acceptance.done()
            else None
        )
        if resolved is None or resolved.state is SemanticAcceptanceState.ACCEPTED:
            synthesis_task = owner.start_tts_if_permitted(
                candidate_id, generation, mode, resolved is not None, synthesize
            )
        peak = owner.active_speculative_tts_count
        acceptance = resolved if resolved is not None else await pending_acceptance
        if (
            acceptance.utterance_id != utterance.utterance_id
            or acceptance.semantic_plan_id != candidate.speech_plan_id
        ):
            raise ValueError("先行合成候補と採用結果の識別子が一致しません")
        before_acceptance = await runtime.candidate(candidate_id)
        if acceptance.state is not SemanticAcceptanceState.ACCEPTED:
            await tasks.cancel_candidate(candidate_id)
            await discarder.discard_current(
                candidate_id, generation, PreparedAudioDiscardReason.SEMANTIC_REJECTED
            )
        else:
            if synthesis_task is None:
                synthesis_task = owner.start_tts_if_permitted(
                    candidate_id, generation, mode, True, synthesize
                )
            if synthesis_task is not None:
                await synthesis_task
            owner.complete_preparation(candidate_id, generation)
    finally:
        if session is None:
            await tasks.shutdown()
        else:
            await tasks.cancel_candidate(candidate_id)
        if synthesis_task is not None:
            await asyncio.gather(synthesis_task, return_exceptions=True)
            synthesis_failed = (
                not synthesis_task.cancelled() and synthesis_task.exception() is not None
            )
    return (
        acceptance,
        result,
        _project(
            {
                "mode": mode,
                "synthesis_failed": synthesis_failed,
                "speculative_count_after_start": peak,
                "speculative_count_after_settlement": owner.active_speculative_tts_count,
                "admission_count_after_settlement": admission.active_count,
                "pending_task_count": tasks.pending_task_count,
                "candidate_before_acceptance_commit": before_acceptance,
            }
        ),
    )
