"""確定Speech intentを既存Ownerの公開APIとPresentation Supervisorへ接続する。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import cast

from app.composition.presentation_notification import CorePresentationNotification
from app.composition.speech_feedback import (
    CoreSpeechFeedback,
    ObservedSpeechPresentationBoundary,
    SpeechFactDeliveryDisposition,
)
from app.composition.speech_preparation import (
    PendingPreparedAudio,
    PendingSpeechAudioOwner,
    SpeechPreparationCleanupError,
    finish_cleanup,
)
from app.domain.activity_execution.observation import ObservedExecutionFactRecord
from app.domain.brain_integration import BrainIntegrationWork
from app.domain.character_language import (
    CharacterLanguageContextSnapshot,
    CharacterLanguageRealizer,
    CharacterUtterance,
)
from app.domain.executive import CommittedExecutiveDecision, ExecutiveIntentKind
from app.domain.semantic_verification import (
    SemanticAcceptanceState,
    SemanticVerificationContextSnapshot,
    SemanticVerificationRun,
    SemanticVerifier,
)
from app.domain.speech_performance import SpeechPerformancePlan, SpeechPerformancePlanner
from app.domain.speech_performance.contracts import SpeechPerformanceContextSnapshot
from app.domain.speech_runtime.admission import (
    SpeechPreparationAdmission,
)
from app.domain.speech_runtime.contracts import (
    AudioReadinessState,
    CandidateLifecycle,
    PreparedSpeechCandidate,
    SemanticRepairAttempt,
    SemanticRepairDisposition,
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
    PreparedAudioDiscardPort,
    PreparedAudioDiscardReason,
)
from app.domain.speech_runtime.orchestrator import SpeechPreparationOrchestrator
from app.domain.speech_runtime.policy import SpeechCandidatePriority
from app.domain.speech_runtime.presentation import SpeechPresentationExecutor
from app.domain.speech_runtime.repair import SemanticRepairEvidence, SpeechSemanticRepairExecutor
from app.domain.speech_runtime.runtime import SpeechRuntime
from app.domain.speech_runtime.tasks import CandidateTaskKey, CandidateTaskRegistry
from app.domain.speech_semantics import SpeechSemanticPlan, SpeechSemanticsPlanner
from app.domain.speech_semantics.contracts import SpeechSemanticContextSnapshot
from app.domain.speech_semantics.production import SpeechSemanticContextBuilder
from app.infrastructure.speech_presentation.supervisor import SpeechPresentationWorkerSupervisor
from app.runtime.kernel import CancellationToken


@dataclass(frozen=True, slots=True)
class CoreSpeechContextReaders:
    """構成元が明示登録する既存Ownerのsnapshot読取。値のdefaultを発明しない。"""

    character: Callable[[SpeechSemanticPlan, str], Awaitable[CharacterLanguageContextSnapshot]]
    verification: Callable[
        [SpeechSemanticPlan, CharacterUtterance, str],
        Awaitable[SemanticVerificationContextSnapshot],
    ]
    performance: Callable[[CharacterUtterance, str], SpeechPerformanceContextSnapshot]
    presentation: Callable[[PreparedSpeechCandidate], Awaitable[SpeechPresentationCommitState]]
    output: Callable[
        [CharacterUtterance, SpeechPerformancePlan],
        Awaitable[tuple[SpeechPresentationMode, str | None]],
    ]


@dataclass
class CoreSpeechPipeline:
    """長いawaitをOwner lockへ入れず、意味判断と資源管理を既存Ownerへ委譲する。"""

    context: SpeechSemanticContextBuilder
    semantics: SpeechSemanticsPlanner
    character: CharacterLanguageRealizer
    verifier: SemanticVerifier
    performance: SpeechPerformancePlanner
    runtime: SpeechRuntime
    executor: SpeechPresentationExecutor
    boundary: SpeechPresentationWorkerSupervisor
    readers: CoreSpeechContextReaders
    clock: Callable[[], datetime]
    notification: Callable[
        [BrainIntegrationWork, CommittedExecutiveDecision, str], CorePresentationNotification
    ]
    priority: SpeechCandidatePriority
    expiry_policy_ref: str
    admission: SpeechPreparationAdmission
    discarder: PreparedAudioDiscarder
    discard_port: PreparedAudioDiscardPort
    output_modes: tuple[SpeechPresentationMode, ...]
    tts_mode: TTSPreparationMode = TTSPreparationMode.AFTER_SEMANTIC_ACCEPTANCE
    reflection_observer: (
        Callable[[BrainIntegrationWork, ObservedExecutionFactRecord], None] | None
    ) = None
    evidence_sink: Callable[[str, object], None] | None = None
    evidence_failed: bool = field(default=False, init=False)

    _tasks: CandidateTaskRegistry = field(default_factory=CandidateTaskRegistry, init=False)
    _runs: CandidateTaskRegistry = field(default_factory=CandidateTaskRegistry, init=False)
    _orchestrator: SpeechPreparationOrchestrator = field(init=False)
    _audio: PendingSpeechAudioOwner = field(init=False)
    _closed: bool = field(default=False, init=False)
    _cleanup_failed: bool = field(default=False, init=False)
    _generations: dict[str, int] = field(default_factory=dict, init=False)
    _discard_reasons: dict[str, PreparedAudioDiscardReason] = field(
        default_factory=dict, init=False
    )

    def __post_init__(self) -> None:
        if not self.output_modes or any(
            mode not in (SpeechPresentationMode.TEXT_ONLY, SpeechPresentationMode.AUDIO_WITH_TEXT)
            for mode in self.output_modes
        ):
            raise ValueError("Speechの許可提示modeを明示してください")
        if (
            not isinstance(self.tts_mode, TTSPreparationMode)
            or self.tts_mode is TTSPreparationMode.DISABLED
        ):
            raise ValueError("Speech output準備には明示的な実行modeが必要です")
        self._orchestrator = SpeechPreparationOrchestrator(self._tasks, self.admission)
        self._audio = PendingSpeechAudioOwner(self.discard_port)

    @property
    def pending_preparation_tasks(self) -> int:
        return self._tasks.pending_task_count + self._runs.pending_task_count

    async def close(self) -> None:
        self._closed = True
        await finish_cleanup(asyncio.create_task(self._close()))

    async def _close(self) -> None:
        await self._runs.shutdown()
        await self._tasks.shutdown()
        if self._audio.pending_count or self._cleanup_failed:
            raise SpeechPreparationCleanupError("shutdown")

    def _observe(self, stage: str, value: object) -> None:
        """任意の同期観測は意味判断・I/Oを行わず、失敗しても製品結果を変更しない。"""
        if self.evidence_sink is not None and not self.evidence_failed:
            try:
                self.evidence_sink(stage, value)
            except Exception:
                self.evidence_failed = True

    async def execute(
        self,
        work: BrainIntegrationWork,
        decision: CommittedExecutiveDecision,
        intent_id: str,
        cancellation: CancellationToken,
    ) -> CoreSpeechFeedback:
        if self._closed:
            raise ValueError("Speech preparationは終了しています")
        policy = self.admission.policy
        if not self.runtime.operational_policy.same_generation(
            policy.policy_id, policy.policy_revision
        ):
            raise ValueError("Speech preparationのpolicy generationが一致しません")
        key = decision.decision_id + ":" + intent_id
        task = self._runs.start(
            CandidateTaskKey(key, 1, "pipeline"),
            self._prepare(work, decision, intent_id, cancellation),
        )
        watcher = asyncio.create_task(cancellation.wait())
        try:
            await asyncio.wait((task, watcher), return_when=asyncio.FIRST_COMPLETED)
            if cancellation.cancelled:
                raise asyncio.CancelledError
            return cast(CoreSpeechFeedback, await task)
        finally:

            async def cleanup() -> None:
                watcher.cancel()
                if not task.done():
                    task.cancel()
                results = await asyncio.gather(task, watcher, return_exceptions=True)
                if isinstance(results[0], SpeechPreparationCleanupError):
                    raise results[0]

            await finish_cleanup(asyncio.create_task(cleanup()))

    async def _prepare(
        self,
        work: BrainIntegrationWork,
        decision: CommittedExecutiveDecision,
        intent_id: str,
        cancellation: CancellationToken,
    ) -> CoreSpeechFeedback:
        if not isinstance(self.boundary, SpeechPresentationWorkerSupervisor):
            raise ValueError("Presentationは既存process Supervisorの明示登録が必要です")
        intent = next((i for i in decision.candidate.intents if i.intent_id == intent_id), None)
        if intent is None or intent.kind is not ExecutiveIntentKind.SPEECH:
            raise ValueError("確定判断のSpeech intentが必要です")
        key = decision.decision_id + ":" + intent_id

        def check_cancel() -> None:
            if cancellation.cancelled:
                raise asyncio.CancelledError

        async def initial() -> object:
            check_cancel()
            snapshot = await self.context.build_async(decision, intent_id, captured_at=self.clock())
            self._observe("semantic_context", snapshot)
            plan = await self.semantics.plan(
                snapshot,
                request_id=key + ":meaning-request",
                trace_id=work.envelope.trace_id,
                candidate_id=key + ":meaning",
                plan_id=key + ":plan",
                created_at=self.clock(),
            )
            self._observe("semantic_plan", plan)
            check_cancel()
            character_context = await self.readers.character(plan, work.envelope.trace_id)
            if character_context.semantic_plan != plan:
                raise ValueError("Character文脈のPlanが一致しません")
            self._observe("character_context", character_context)
            utterance = await self.character.realize(
                character_context, utterance_id=key + ":utterance", created_at=self.clock()
            )
            self._observe("utterance", utterance)
            check_cancel()
            return snapshot, plan, character_context, utterance

        first = self._orchestrator.start_preparation(key, 1, self.priority, initial)
        if first is None:
            raise ValueError("Speech preparation容量を超えました")
        generation = 1
        registered = False
        reason = PreparedAudioDiscardReason.CANDIDATE_CANCELLED
        terminal = CandidateLifecycle.CANCELLED
        try:
            snapshot, plan, character_context, utterance = cast(
                tuple[
                    SpeechSemanticContextSnapshot,
                    SpeechSemanticPlan,
                    CharacterLanguageContextSnapshot,
                    CharacterUtterance,
                ],
                await first,
            )
            policy = self.runtime.operational_policy
            revisions = plan.candidate.revisions
            now = self.clock()
            candidate = PreparedSpeechCandidate(
                candidate_id=key,
                preparation_id=key + ":preparation",
                source_decision_id=decision.decision_id,
                source_event_ids=plan.candidate.source_event_ids,
                speech_plan_id=plan.plan_id,
                utterance_id=utterance.utterance_id,
                performance_plan_id=None,
                source_context_revision=revisions.source_context_revision,
                goal_revision=revisions.goal_revision,
                attention_revision=revisions.attention_revision,
                priority=self.priority,
                interruptibility=character_context.interruptibility,
                expiry_policy_ref=self.expiry_policy_ref,
                runtime_policy_id=policy.policy_id,
                runtime_policy_revision=policy.policy_revision,
                required_preconditions=tuple(p.precondition_id for p in intent.preconditions),
                semantic_requirement=SemanticVerificationRequirement.REQUIRED,
                semantic_acceptance_id=None,
                prepared_audio_ref=None,
                presentation_modes=self.output_modes,
                readiness=SpeechComponentReadiness(
                    SpeechReadinessState.READY,
                    SpeechReadinessState.READY,
                    VerifierReadinessState.PENDING,
                    SpeechReadinessState.PENDING,
                    AudioReadinessState.NOT_REQUESTED,
                ),
                lifecycle=CandidateLifecycle.PREPARING,
                created_at=now,
                updated_at=now,
                prepared_at=None,
                character_definition_revision=utterance.candidate.character_definition_revision,
            )
            await self.runtime.register(candidate)
            registered = True
            self._generations[key] = generation
            candidate, generation = await self._parallel_prepare(
                key, work, plan, character_context, utterance, cancellation, snapshot
            )
            self._observe("prepared_candidate", candidate)
            current = await self.readers.presentation(candidate)
            self._observe("presentation_context", current)
            check_cancel()
            if snapshot.generation is not None:
                snapshot.generation.require_current()
            downstream = self.notification(work, decision, key + ":presentation")
            if (
                downstream.presentation_id != key + ":presentation"
                or downstream.provenance.source_decision_id != decision.decision_id
                or downstream.provenance.source_event_ids != decision.candidate.source_event_ids
                or downstream.provenance.trace_id != work.envelope.trace_id
                or downstream.root_trigger_id
                != (work.envelope.root_trigger_id or work.envelope.trigger_id)
            ):
                raise ValueError("Presentation還流の元Brain相関が一致しません")

            def deliver(record: ObservedExecutionFactRecord) -> SpeechFactDeliveryDisposition:
                if self.reflection_observer is not None:
                    self.reflection_observer(work, record)
                return downstream.deliver(record)

            feedback = CoreSpeechFeedback(
                self.runtime,
                downstream.authority,
                key + ":presentation",
                downstream.provenance,
                deliver,
            )
            await self.executor.commit_and_present(
                candidate_id=key,
                state=current,
                presentation_id=key + ":presentation",
                adapter=ObservedSpeechPresentationBoundary(self.boundary, feedback),
            )
            return feedback
        except BaseException as error:
            if not isinstance(error, asyncio.CancelledError):
                reason = self._discard_reasons.get(key, reason)
                terminal = CandidateLifecycle.FAILED
            raise
        finally:

            async def cleanup() -> None:
                await self._tasks.cancel_candidate(key)
                direct_failed = False
                # repair前世代を含め、受領した元identityだけを回収する。
                current_generation = self._generations.get(key, generation)
                cleanup_reason = reason
                if registered:
                    if not await self.runtime.is_current_generation(key, current_generation):
                        cleanup_reason = PreparedAudioDiscardReason.CANDIDATE_SUPERSEDED
                    elif await self.runtime.operational_failure(key) is not None:
                        cleanup_reason = PreparedAudioDiscardReason.CANDIDATE_STALE
                for old in range(1, current_generation + 1):
                    try:
                        await self._audio.discard(key, old, cleanup_reason)
                    except SpeechPreparationCleanupError:
                        direct_failed = True
                if (
                    registered
                    and await self.runtime.is_current_generation(key, current_generation)
                    and key in await self.runtime.active_candidate_ids()
                ):
                    current = await self.runtime.candidate(key)
                    if current.lifecycle is not CandidateLifecycle.PRESENTING:
                        try:
                            await self.discarder.discard_current(
                                key, current_generation, cleanup_reason
                            )
                        except BaseException:
                            direct_failed = True
                        else:
                            final_state = terminal
                            if await self.runtime.operational_failure(key) is not None:
                                final_state = CandidateLifecycle.STALE
                            await self.runtime.cancel(
                                key, final_state, expected_generation=current_generation
                            )
                self._generations.pop(key, None)
                self._discard_reasons.pop(key, None)
                if direct_failed:
                    self._cleanup_failed = True
                    raise SpeechPreparationCleanupError(cleanup_reason.value)

            await finish_cleanup(asyncio.create_task(cleanup()))

    async def _parallel_prepare(
        self,
        key: str,
        work: BrainIntegrationWork,
        plan: SpeechSemanticPlan,
        character_context: CharacterLanguageContextSnapshot,
        utterance: CharacterUtterance,
        cancellation: CancellationToken,
        snapshot: SpeechSemanticContextSnapshot,
    ) -> tuple[PreparedSpeechCandidate, int]:
        generation = self.runtime.generation(key)
        repair = SpeechSemanticRepairExecutor(self.runtime, self._tasks, self.discarder)
        while True:
            suffix = "" if generation == 1 else f":repair-{generation - 1}"

            async def verify(
                utterance: CharacterUtterance = utterance, suffix: str = suffix
            ) -> object:
                context = await self.readers.verification(plan, utterance, work.envelope.trace_id)
                if context.semantic_plan != plan or context.utterance != utterance:
                    raise ValueError("Verifier文脈のPlan/Utteranceが一致しません")
                self._observe("verification_context", context)
                try:
                    value = await self.verifier.verify(
                        context,
                        blind_observation_id=key + ":blind" + suffix,
                        relation_observation_id=key + ":relation" + suffix,
                        semantic_observation_id=key + ":semantic-observation" + suffix,
                        acceptance_id=key + ":acceptance" + suffix,
                        created_at=self.clock(),
                    )
                except Exception:
                    self._discard_reasons[key] = PreparedAudioDiscardReason.VERIFIER_FAILED
                    raise
                self._observe("verification", value)
                return value

            async def perform(
                utterance: CharacterUtterance = utterance, suffix: str = suffix
            ) -> object:
                context = self.readers.performance(utterance, work.envelope.trace_id)
                if context.utterance != utterance:
                    raise ValueError("Performance文脈のUtteranceが一致しません")
                self._observe("performance_context", context)
                value = self.performance.plan_snapshot(
                    context, key + ":performance" + suffix, self.clock()
                )
                self._observe("performance_plan", value)
                return value

            verifier_task, performance_task = self._orchestrator.fan_out_after_character(
                key, generation, verify, perform
            )
            performance = cast(SpeechPerformancePlan, await performance_task)

            async def output(
                utterance: CharacterUtterance = utterance,
                performance: SpeechPerformancePlan = performance,
                generation: int = generation,
            ) -> object:
                mode, audio_ref = await self.readers.output(utterance, performance)
                # awaitへ戻らず受領を記録するため、親取消との競合でも元identityを失わない。
                if audio_ref is not None:
                    self._audio.receive(
                        PendingPreparedAudio(
                            key,
                            generation,
                            utterance.utterance_id,
                            performance.performance_plan_id,
                            audio_ref,
                        )
                    )
                if (
                    mode not in self.output_modes
                    or (mode is SpeechPresentationMode.TEXT_ONLY and audio_ref is not None)
                    or (mode is SpeechPresentationMode.AUDIO_WITH_TEXT and audio_ref is None)
                ):
                    raise ValueError("提示modeと準備済み音声の組が不正です")
                return mode

            output_task = self._orchestrator.start_tts_if_permitted(
                key, generation, self.tts_mode, False, output
            )
            verified = cast(SemanticVerificationRun, await verifier_task)
            if verified.acceptance.state is not SemanticAcceptanceState.ACCEPTED:
                # repairによる世代更新より先に、旧outputの終了と資源を回収する。
                if output_task is not None:
                    output_task.cancel()
                    await asyncio.gather(output_task, return_exceptions=True)
                await self._audio.discard(
                    key, generation, PreparedAudioDiscardReason.SEMANTIC_REJECTED
                )
                next_attempt: SemanticRepairAttempt | None = None

                async def request_repair(attempt: SemanticRepairAttempt) -> None:
                    nonlocal next_attempt
                    next_attempt = attempt

                if snapshot.generation is not None:
                    snapshot.generation.require_current()
                disposition = await repair.handle_verifier_result(
                    candidate_id=key,
                    generation=generation,
                    semantic_accepted=False,
                    semantic_acceptance_id=verified.acceptance.acceptance_id,
                    verifier_execution_failed=False,
                    speech_plan_stale=False,
                    evidence=SemanticRepairEvidence(
                        tuple(c.value for c in verified.acceptance.rejection_categories),
                        (verified.acceptance.acceptance_id,),
                    ),
                    repair_character=request_repair,
                )
                if disposition is not SemanticRepairDisposition.REPAIR_ONCE or next_attempt is None:
                    raise ValueError("Verifierが発話を受理しませんでした")
                generation = self.runtime.generation(key)
                self._generations[key] = generation
                character_context = replace(
                    character_context,
                    request_id=key + f":repair-request-{generation}",
                    prior_realizations=(),
                    captured_at=self.clock(),
                )

                async def regenerate(
                    character_context: CharacterLanguageContextSnapshot = character_context,
                    generation: int = generation,
                ) -> object:
                    self._observe("character_context", character_context)
                    value = await self.character.realize(
                        character_context,
                        utterance_id=key + f":utterance-{generation}",
                        created_at=self.clock(),
                    )
                    self._observe("utterance", value)
                    return value

                regenerated = self._orchestrator.start_preparation(
                    key, generation, self.priority, regenerate
                )
                if regenerated is None:
                    raise ValueError("Speech repair準備容量を超えました")
                utterance = cast(CharacterUtterance, await regenerated)
                continue
            if output_task is None:
                output_task = self._orchestrator.start_tts_if_permitted(
                    key, generation, self.tts_mode, True, output
                )
            if output_task is None:
                raise ValueError("Speech output準備が許可されていません")
            await output_task
            if cancellation.cancelled:
                raise asyncio.CancelledError
            if snapshot.generation is not None:
                snapshot.generation.require_current()
            if not await self.runtime.is_current_generation(key, generation):
                raise ValueError("Speech準備の世代が更新されました")
            pending = self._audio.result(key, generation)
            readiness = SpeechComponentReadiness(
                SpeechReadinessState.READY,
                SpeechReadinessState.READY,
                VerifierReadinessState.ACCEPTED,
                SpeechReadinessState.READY,
                AudioReadinessState.READY
                if pending is not None
                else AudioReadinessState.NOT_REQUESTED,
            )
            accepted = await self.runtime.commit_generation_result(
                key,
                generation,
                readiness=readiness,
                utterance_id=utterance.utterance_id,
                performance_plan_id=performance.performance_plan_id,
                semantic_acceptance_id=verified.acceptance.acceptance_id,
                prepared_audio_ref=pending.audio_ref if pending is not None else None,
            )
            if accepted is None:
                raise ValueError("Speech音声の世代fenceが採用を拒否しました")
            if (
                accepted.utterance_id != utterance.utterance_id
                or accepted.performance_plan_id != performance.performance_plan_id
                or accepted.prepared_audio_ref
                != (pending.audio_ref if pending is not None else None)
            ):
                raise ValueError("Speech音声の採用identityが一致しません")
            self._audio.transferred(key, generation)
            if await self.runtime.queue_for_generation(key, generation) is None:
                raise ValueError("Speech候補をqueueへ採用できません")
            if await self.runtime.begin_revalidation(key, generation) is None:
                raise ValueError("Speech候補の再照合を開始できません")
            current = await self.readers.presentation(await self.runtime.candidate(key))
            candidate = await self.runtime.revalidate_current(key, generation, current)
            if candidate is None:
                raise ValueError("Speech候補の現在性を確認できません")
            self._orchestrator.complete_preparation(key, generation)
            return candidate, generation
