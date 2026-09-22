"""確定Speech intentを既存Ownerの公開APIとPresentation Supervisorへ接続する。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime

from app.composition.presentation_notification import CorePresentationNotification
from app.composition.speech_feedback import CoreSpeechFeedback, ObservedSpeechPresentationBoundary
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
    SemanticVerifier,
)
from app.domain.speech_performance import SpeechPerformancePlan, SpeechPerformancePlanner
from app.domain.speech_performance.contracts import SpeechPerformanceContextSnapshot
from app.domain.speech_runtime.admission import (
    AdmittedPreparationExecutor,
    SpeechPreparationAdmission,
)
from app.domain.speech_runtime.contracts import (
    AudioReadinessState,
    CandidateLifecycle,
    PreparedSpeechCandidate,
    SemanticVerificationRequirement,
    SpeechComponentReadiness,
    SpeechPresentationCommitState,
    SpeechPresentationMode,
    SpeechReadinessState,
    VerifierReadinessState,
)
from app.domain.speech_runtime.discard import PreparedAudioDiscarder, PreparedAudioDiscardReason
from app.domain.speech_runtime.policy import SpeechCandidatePriority
from app.domain.speech_runtime.presentation import SpeechPresentationExecutor
from app.domain.speech_runtime.runtime import SpeechRuntime
from app.domain.speech_semantics import SpeechSemanticPlan, SpeechSemanticsPlanner
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
    evidence_sink: Callable[[str, object], None] | None = None
    evidence_failed: bool = field(default=False, init=False)

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
        policy = self.admission.policy
        if not self.runtime.operational_policy.same_generation(
            policy.policy_id, policy.policy_revision
        ):
            raise ValueError("Speech preparationのpolicy generationが一致しません")
        result = await AdmittedPreparationExecutor(self.admission).run(
            self.priority, lambda: self._prepare(work, decision, intent_id, cancellation)
        )
        if result is None:
            raise ValueError("Speech preparation容量を超えました")
        return result

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
                import asyncio

                raise asyncio.CancelledError

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
        performance_context = self.readers.performance(utterance, work.envelope.trace_id)
        if performance_context.utterance != utterance:
            raise ValueError("Performance文脈のUtteranceが一致しません")
        self._observe("performance_context", performance_context)
        performance = self.performance.plan_snapshot(
            performance_context, key + ":performance", self.clock()
        )
        self._observe("performance_plan", performance)
        verification_context = await self.readers.verification(
            plan, utterance, work.envelope.trace_id
        )
        if (
            verification_context.semantic_plan != plan
            or verification_context.utterance != utterance
        ):
            raise ValueError("Verifier文脈のPlan/Utteranceが一致しません")
        self._observe("verification_context", verification_context)
        verified = await self.verifier.verify(
            verification_context,
            blind_observation_id=key + ":blind",
            relation_observation_id=key + ":relation",
            semantic_observation_id=key + ":semantic-observation",
            acceptance_id=key + ":acceptance",
            created_at=self.clock(),
        )
        self._observe("verification", verified)
        if verified.acceptance.state is not SemanticAcceptanceState.ACCEPTED:
            raise ValueError("Verifierが発話を受理しませんでした")
        check_cancel()
        mode, audio_ref = await self.readers.output(utterance, performance)
        check_cancel()
        if (
            (mode is SpeechPresentationMode.TEXT_ONLY and audio_ref is not None)
            or (mode is SpeechPresentationMode.AUDIO_WITH_TEXT and audio_ref is None)
            or mode
            not in (SpeechPresentationMode.TEXT_ONLY, SpeechPresentationMode.AUDIO_WITH_TEXT)
        ):
            raise ValueError("提示modeと準備済み音声の組が不正です")
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
            performance_plan_id=performance.performance_plan_id,
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
            semantic_acceptance_id=verified.acceptance.acceptance_id,
            prepared_audio_ref=audio_ref,
            presentation_modes=(mode,),
            readiness=SpeechComponentReadiness(
                SpeechReadinessState.READY,
                SpeechReadinessState.READY,
                VerifierReadinessState.ACCEPTED,
                SpeechReadinessState.READY,
                AudioReadinessState.READY
                if audio_ref is not None
                else AudioReadinessState.NOT_REQUESTED,
            ),
            lifecycle=CandidateLifecycle.READY_TO_PRESENT,
            created_at=now,
            updated_at=now,
            prepared_at=now,
            character_definition_revision=utterance.candidate.character_definition_revision,
        )
        await self.runtime.register(candidate)
        self._observe("prepared_candidate", candidate)
        try:
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
            feedback = CoreSpeechFeedback(
                self.runtime,
                downstream.authority,
                key + ":presentation",
                downstream.provenance,
                downstream.deliver,
            )
            await self.executor.commit_and_present(
                candidate_id=key,
                state=current,
                presentation_id=key + ":presentation",
                adapter=ObservedSpeechPresentationBoundary(self.boundary, feedback),
            )
            return feedback
        except BaseException:
            await self.discarder.discard_current(
                key, self.runtime.generation(key), PreparedAudioDiscardReason.CANDIDATE_CANCELLED
            )
            if key in await self.runtime.active_candidate_ids():
                await self.runtime.cancel(key)
            raise
