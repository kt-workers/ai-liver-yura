"""実Planner/Ownerとprocess Presentationを同じproduction pipelineで結合する。"""

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

import pytest

from app.composition.execution_observation import SPEECH_OBSERVATION_POLICY
from app.composition.input_reference_context import CoreInputReferenceContextBinding
from app.composition.presentation_notification import CorePresentationNotification
from app.composition.speech import CoreSpeechContextReaders, CoreSpeechPipeline
from app.domain.activity_execution import ActivityExecutionAuthority, ExecutionObservationProvenance
from app.domain.attention import AttentionSourceKind
from app.domain.attention import AttentionTransitionOperation as Op
from app.domain.brain_integration import (
    BrainIntegrationLane,
    BrainIntegrationModule,
    BrainIntegrationWork,
    BrainWorkEnvelope,
    BrainWorkPriority,
)
from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY as BOUNDS
from app.domain.character_language import (
    CharacterLanguageAuthority,
    CharacterLanguageContextSnapshot,
    CharacterLanguageRealizer,
)
from app.domain.contracts import CapabilityAvailability
from app.domain.goals import GoalCommitmentStore
from app.domain.input_gateway import InputModality, InputPermission, InputSourceState
from app.domain.llm import StructuredPayload
from app.domain.semantic_verification import (
    BLIND_ROLE_ID,
    SemanticVerificationAuthority,
    SemanticVerificationContextSnapshot,
    SemanticVerifier,
)
from app.domain.speech_performance import SpeechPerformanceContextSnapshot
from app.domain.speech_performance.planner import SpeechPerformancePlanner
from app.domain.speech_performance.policy import yura_revision_1_policy
from app.domain.speech_runtime.policy import SpeechCandidatePriority
from app.domain.speech_runtime.presentation import SpeechPresentationExecutor
from app.domain.speech_runtime.runtime import SpeechRuntime
from app.domain.speech_runtime.tasks import CandidateTaskRegistry
from app.domain.speech_semantics import SpeechSemanticAuthority, SpeechSemanticsPlanner
from tests.domain.attention.test_attention_turn_store import signal, transition
from tests.domain.character_language.test_character_language import candidate, current, profile
from tests.domain.character_language.test_character_language import policy as character_policy
from tests.domain.character_language.test_character_language import result_for as character_result
from tests.domain.input_meaning.test_input_meaning import policy as input_policy
from tests.domain.semantic_verification.test_semantic_verification import (
    TEXT,
    _eligible,
    _SequencePort,
    verification_policy,
)
from tests.domain.speech_runtime.policy_fixtures import runtime_policy
from tests.domain.speech_runtime.test_presentation import _state
from tests.domain.speech_semantics.test_speech_semantics import policy as semantics_policy
from tests.domain.speech_semantics.test_speech_semantics import result_for as semantics_result
from tests.infrastructure.speech_presentation.test_process import boundary
from tests.infrastructure.speech_presentation.test_process import policy as timeout_policy
from tests.system_integration.test_presentation_notification import Normalizer
from tests.system_integration.test_speech_semantics_policy import (
    binding,
    committed,
    speech_candidate,
)


def now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "slow_stage", [None, "character", "verification", "playback", "cancel", "stale"]
)
async def test_full_owner_pipeline_and_presentation_feedback(slow_stage: str | None) -> None:
    b = binding()
    d = await committed(b, "goal-1")
    intent = d.candidate.intents[0]
    semctx = await b.context_builder.build_async(d, intent.intent_id, captured_at=now())
    from app.composition.speech_semantics_policy import bind_speech_semantics_policy_v1
    from app.composition.speech_semantics_sources import ProductionSpeechSources
    from app.domain.executive import CommitmentTransitionOperation, GoalTransitionOperation
    from app.domain.goals import GoalCommitmentSnapshot
    from tests.domain.goals.test_goal_commitment_store import commitment_transition, goal_transition
    from tests.domain.goals.test_goal_commitment_store import decision as goal_decision
    from tests.helpers.speech_production import production_sources

    original_sources = production_sources()
    initial = original_sources._goals.snapshot()
    late_goals = GoalCommitmentStore(GoalCommitmentSnapshot(4, (), (), initial.updated_at))
    sources = ProductionSpeechSources(
        goals=late_goals, memory=original_sources._memory, execution=ActivityExecutionAuthority()
    )
    b = bind_speech_semantics_policy_v1(b.owner, sources=sources)
    contexts: dict[str, Any] = {}

    class Live:
        async def current_revisions(self, s: Any) -> Any:
            return s.revisions

        async def current_state(self, s: Any) -> Any:
            return (
                current(s)
                if isinstance(s, CharacterLanguageContextSnapshot)
                else _eligible(s, revisions=s.revisions)
            )

    class Port:
        async def invoke(self, request: Any) -> Any:
            value: Any
            if request.role_id.startswith("speech.semantics") or request.role_id.startswith(
                "speech_semantics"
            ):
                value = replace(
                    speech_candidate(semctx, 0, 0),
                    created_at=now(),
                    self_disclosure=semctx.self_disclosure_policy,
                ).to_dict()
                value.pop("created_at", None)
                result = semantics_result(request, value)
            elif "character" in request.role_id:
                ctx = contexts["character"]
                props = tuple(p.proposition_id for p in ctx.semantic_plan.candidate.propositions)
                value = replace(
                    candidate(ctx, text=TEXT, refs=props),
                    candidate_id=ctx.semantic_plan.plan_id + ":character-candidate",
                    created_at=now(),
                ).to_dict()
                value.pop("created_at", None)
                result = character_result(request, value)
            else:
                ctx = contexts["verification"]
                from tests.domain.semantic_verification.test_semantic_verification import (
                    NOW as VERIFIER_NOW,
                )

                result = _SequencePort(ctx)._result_for(replace(request, created_at=VERIFIER_NOW))
                assert result.output is not None
                from app.domain.contracts.common import thaw_json

                value = thaw_json(result.output.value)
                if request.role_id != BLIND_ROLE_ID:
                    props = ctx.semantic_plan.candidate.propositions
                    value["blind_observation_id"] = (
                        d.decision_id + ":" + intent.intent_id + ":blind"
                    )
                    base = value["proposition_observations"][0]
                    value["proposition_observations"] = [
                        dict(base, proposition_id=p.proposition_id) for p in props
                    ]
                    value["blind_unit_accounting"][0]["proposition_ids"] = [
                        p.proposition_id for p in props
                    ]
                    for name in (
                        "request_id",
                        "semantic_plan_id",
                        "utterance_id",
                        "blind_observation_id",
                    ):
                        value.pop(name)
                    for item in value["proposition_observations"]:
                        item.pop("evidence_refs")
                        item.pop("supporting_blind_unit_ids")
                result = replace(result, output=StructuredPayload(result.output.schema_id, value))
            return replace(result, started_at=request.created_at, completed_at=now())

    live, port = Live(), Port()
    blocked, release = asyncio.Event(), asyncio.Event()

    async def pause(stage: str) -> None:
        if slow_stage == stage or (slow_stage in ("cancel", "stale") and stage == "character"):
            blocked.set()
            await release.wait()

    async def character_context(plan: Any, trace: str) -> Any:
        await pause("character")
        from app.domain.llm import LLMInterruptibility, LLMPriority

        value = CharacterLanguageContextSnapshot(
            plan.plan_id + ":character-request",
            plan,
            profile(),
            (),
            LLMPriority.FOREGROUND,
            LLMInterruptibility.INTERRUPTIBLE,
            now(),
            trace,
        )
        contexts["character"] = value
        return value

    async def verification_context(plan: Any, utterance: Any, trace: str) -> Any:
        await pause("verification")
        from app.domain.llm import LLMInterruptibility, LLMPriority

        value = SemanticVerificationContextSnapshot(
            plan.plan_id + ":verification",
            plan.plan_id + ":blind-request",
            plan.plan_id + ":relation-request",
            plan,
            utterance,
            LLMPriority.FOREGROUND,
            LLMInterruptibility.INTERRUPTIBLE,
            now(),
            trace,
        )
        contexts["verification"] = value
        return value

    perf_policy = yura_revision_1_policy()

    def performance_context(utterance: Any, trace: str) -> Any:
        r = utterance.candidate.revisions
        return SpeechPerformanceContextSnapshot(
            "performance-request",
            utterance,
            None,
            None,
            (),
            r.source_context_revision,
            r.goal_revision,
            r.attention_revision,
            now(),
            trace,
            perf_policy.policy_id,
            perf_policy.policy_revision,
        )

    async def presentation_context(c: Any) -> Any:
        return replace(
            _state(),
            source_context_revision=c.source_context_revision,
            goal_revision=c.goal_revision,
            attention_revision=c.attention_revision,
            satisfied_preconditions=c.required_preconditions,
            semantic_acceptance_id=c.semantic_acceptance_id,
            performance_plan_id=c.performance_plan_id,
            character_definition_revision=c.character_definition_revision,
        )

    owner = ActivityExecutionAuthority(observation_policy=SPEECH_OBSERVATION_POLICY)
    from tests.domain.attention.test_attention_turn_store import attention_store

    attention = attention_store()
    event = d.candidate.source_event_ids[0]
    attention.offer(
        signal(event, AttentionSourceKind.USER_INTERACTION, seconds=40, trusted_direct_user=True)
    )
    s = attention.snapshot()
    attention.apply(
        1,
        tuple(
            replace(transition(op, s.revision, 1, value=event), occurred_at=now())
            for op in (Op.ASSIGN_TURN, Op.SET_RESPONSE_OBLIGATION)
        ),
    )
    reference = CoreInputReferenceContextBinding(
        GoalCommitmentStore(), owner, input_policy(), BOUNDS
    )
    from pathlib import Path

    from app.composition.accepted_input import CoreAcceptedInputStore
    from app.composition.cognition_configuration import CoreCognitionConfiguration
    from app.config.minimum_brain import load_minimum_brain_config
    from app.domain.appraisal import InternalStateReducer
    from app.domain.brain_integration import BrainIntegrationRuntime
    from app.domain.contracts.preconditions import PreconditionSourceRouter
    from app.domain.executive import ExecutiveIntentRequirementsPolicy, ExecutiveRequirementsOwner
    from app.domain.plugin_registry import PluginRegistryAuthority
    from app.runtime.kernel import SystemRuntimeClock
    from tests.domain.appraisal.test_appraisal_paths import policy as appraisal_policy
    from tests.domain.appraisal.test_appraisal_paths import state
    from tests.domain.executive.test_executive import policy as executive_policy
    from tests.system_integration import test_core_cognition as core

    requirements = ExecutiveRequirementsOwner(BOUNDS)
    requirements.publish(ExecutiveIntentRequirementsPolicy("wait-only", 1, ()))
    config = CoreCognitionConfiguration(
        appraisal_policy(),
        executive_policy(),
        InternalStateReducer(replace(state(), source_context_revision=0)),
        attention,
        requirements,
        PluginRegistryAuthority(),
        PreconditionSourceRouter(()),
        (),
        (),
    )
    cognitive_port = core.Port()
    brain = BrainIntegrationRuntime(
        SystemRuntimeClock(),
        load_minimum_brain_config(
            Path("resources/config/v2/minimum_brain.yaml").read_bytes()
        ).integration_policy,
    )

    class NoMeaning:
        def is_fresh(self, w: Any) -> bool:
            return True

        async def execute(self, w: Any, c: Any) -> Any:
            raise AssertionError("SUBSYSTEMはInput Meaningを通しません")

    notifications = []

    def submit(a: Any, r: str) -> Any:
        notifications.append(a)
        return cognition.submit_input(a, root_trigger_id=r)

    def notify(work: Any, decision: Any, presentation_id: str) -> Any:
        return CorePresentationNotification(
            owner,
            attention,
            reference,
            Normalizer(),
            InputSourceState(
                "speech",
                "subsystem",
                CapabilityAvailability.AVAILABLE,
                InputPermission.NOT_REQUIRED,
            ),
            ExecutionObservationProvenance(
                decision.decision_id,
                decision.candidate.source_event_ids,
                semctx.revisions,
                work.envelope.trace_id,
            ),
            "root",
            presentation_id,
            submit,
        )

    from app.domain.speech_runtime.admission import SpeechPreparationAdmission
    from app.domain.speech_runtime.contracts import SpeechPresentationMode

    async def output(utterance: Any, performance: Any) -> Any:
        return SpeechPresentationMode.TEXT_ONLY, None

    runtime = SpeechRuntime(
        replace(
            runtime_policy(),
            presentation_timeout=replace(timeout_policy(), text_terminal_timeout_seconds=10)
            if slow_stage == "playback"
            else timeout_policy(),
        )
    )
    tasks = CandidateTaskRegistry()
    supervisor = boundary("hang" if slow_stage == "playback" else "normal")
    from app.domain.speech_runtime.discard import PreparedAudioDiscarder
    from app.domain.speech_runtime.queue import PreparedSpeechQueue, PreparedSpeechQueueCoordinator

    class NoAudio:
        async def discard(self, request: Any) -> None:
            raise AssertionError("text提示に音声資源はありません")

    discarder = PreparedAudioDiscarder(runtime, NoAudio())
    pipeline = CoreSpeechPipeline(
        b.context_builder,
        SpeechSemanticsPlanner(
            port,
            live,
            SpeechSemanticAuthority(),
            replace(semantics_policy(), meaning_policy=b.owner.publication().value.meaning),
        ),
        CharacterLanguageRealizer(port, live, CharacterLanguageAuthority(), character_policy()),
        SemanticVerifier(port, live, SemanticVerificationAuthority(), verification_policy()),
        SpeechPerformancePlanner(perf_policy),
        runtime,
        SpeechPresentationExecutor(runtime, tasks),
        supervisor,
        CoreSpeechContextReaders(
            character_context,
            verification_context,
            performance_context,
            presentation_context,
            output,
        ),
        now,
        notify,
        SpeechCandidatePriority.FOREGROUND,
        "expiry",
        SpeechPreparationAdmission(runtime.operational_policy),
        discarder,
        NoAudio(),
        (SpeechPresentationMode.TEXT_ONLY,),
    )
    work = BrainIntegrationWork(
        "work",
        BrainIntegrationModule.SPEECH_SEMANTICS,
        BrainIntegrationLane.SPEECH_PREPARATION,
        BrainWorkEnvelope(
            "trace",
            "trigger",
            d.candidate.source_event_ids,
            semctx.revisions.source_context_revision,
            semctx.revisions.goal_revision,
            semctx.revisions.attention_revision,
            BrainWorkPriority.NORMAL,
            now(),
            root_trigger_id="root",
        ),
        d,
    )
    from app.composition.speech_configuration import CoreSpeechConfiguration
    from app.domain.speech_runtime.shutdown import SpeechRuntimeShutdown

    shutdown = SpeechRuntimeShutdown(
        runtime,
        tasks,
        PreparedSpeechQueueCoordinator(
            runtime, PreparedSpeechQueue(runtime.operational_policy), discarder
        ),
        discarder,
    )
    config = replace(
        config,
        speech=CoreSpeechConfiguration(b.executive_evidence, lambda c, r: (pipeline, shutdown)),
    )
    inputs = CoreAcceptedInputStore(32)
    cognition = config.compose(brain, reference, inputs, cognitive_port, SystemRuntimeClock())
    from types import SimpleNamespace

    original_input = core.admission(
        SimpleNamespace(input_context=reference), internal=True, event_id=event
    )
    cognition.register(NoMeaning())
    from tests.domain.activity_execution.test_activity_execution import started

    class Activity:
        def is_fresh(self, w: Any) -> bool:
            return True

        async def execute(self, w: Any, token: Any) -> Any:
            return started(owner)[1]

    brain.register_module(BrainIntegrationModule.ACTIVITY_EXECUTION, Activity())
    await brain.start()
    try:
        assert cognition.submit_input(original_input, root_trigger_id="original-root").accepted
        initial_outcomes = [await asyncio.wait_for(brain.next_outcome(), 3) for _ in range(2)]
        assert all(o.status.value == "completed" for o in initial_outcomes)
        # Core/Speech routeの登録とRuntime起動後に作るGoalを、ID再登録なしで使う。
        assert late_goals.snapshot().goals == ()
        late_goals.apply(
            goal_decision(
                "late-goal",
                4,
                goals=(goal_transition(GoalTransitionOperation.CREATE, 4),),
                commitments=(commitment_transition(CommitmentTransitionOperation.CREATE, 4),),
            )
        )
        d = await committed(b, "goal-1")
        semctx = await b.context_builder.build_async(d, intent.intent_id, captured_at=now())
        assert cognition.speech is not None
        cognition.speech.accept_decision(work, d)
        if slow_stage == "stale":
            await asyncio.wait_for(blocked.wait(), 3)
            with late_goals.finalization_participant.mutation():
                pass
            release.set()
            stale = await asyncio.wait_for(brain.next_outcome(), 3)
            assert stale.status.value == "failed"
            assert notifications == [] and supervisor.active_execution_count == 0
            assert await runtime.active_candidate_ids() == ()
            return
        if slow_stage == "cancel":
            await asyncio.wait_for(blocked.wait(), 3)
            speech_id = d.decision_id + ":" + intent.intent_id + ":speech-work"
            assert brain.cancel(speech_id, "試験取消")
            brain.cancel(speech_id, "再取消")
            cancelled = await asyncio.wait_for(brain.next_outcome(), 3)
            assert cancelled.status.value == "cancelled"
            assert notifications == [] and pipeline.admission.active_count == 0
            assert await runtime.active_candidate_ids() == ()
            return
        if slow_stage in ("character", "verification"):
            await asyncio.wait_for(blocked.wait(), 3)
            assert brain.submit(
                replace(
                    work,
                    work_id="unrelated-activity",
                    module=BrainIntegrationModule.ACTIVITY_EXECUTION,
                    lane=BrainIntegrationLane.COGNITIVE_NORMAL,
                )
            ).accepted
            activity_outcome = await asyncio.wait_for(brain.next_outcome(), 3)
            assert (
                activity_outcome.module is BrainIntegrationModule.ACTIVITY_EXECUTION
                and activity_outcome.status.value == "completed"
            )
            assert cognition.submit_input(
                core.admission(
                    SimpleNamespace(input_context=reference),
                    internal=True,
                    event_id="unrelated-input",
                    trace_id="unrelated",
                ),
                root_trigger_id="unrelated-root",
            ).accepted
            independent = [await asyncio.wait_for(brain.next_outcome(), 3) for _ in range(2)]
            assert {o.module for o in independent} == {
                BrainIntegrationModule.APPRAISAL,
                BrainIntegrationModule.EXECUTIVE,
            }
            assert all(o.status.value == "completed" for o in independent)
            assert pipeline.admission.active_count == 1
            release.set()
        speech_outcome = await asyncio.wait_for(brain.next_outcome(), 3)
        assert speech_outcome.module is BrainIntegrationModule.SPEECH_SEMANTICS
        assert speech_outcome.status.value == "completed"
        from app.composition.speech_feedback import CoreSpeechFeedback

        feedback = speech_outcome.result
        assert isinstance(feedback, CoreSpeechFeedback)
        if slow_stage == "playback":

            async def started_playback() -> None:
                while not notifications:
                    await asyncio.sleep(0.005)

            await asyncio.wait_for(started_playback(), 3)
            from app.domain.speech_runtime.contracts import CandidateLifecycle

            first_id = d.decision_id + ":" + intent.intent_id
            assert (await runtime.candidate(first_id)).lifecycle is CandidateLifecycle.PRESENTING
            intent = replace(intent, intent_id="second-intent")
            d = replace(
                d,
                decision_id="second-decision",
                candidate=replace(d.candidate, intents=(intent,)),
                speech_reference_resolutions=tuple(
                    replace(r, intent_id=intent.intent_id) for r in d.speech_reference_resolutions
                ),
            )
            semctx = await b.context_builder.build_async(d, intent.intent_id, captured_at=now())
            cognition.speech.accept_decision(work, d)

            async def next_prepared() -> Any:
                while True:
                    outcome = await brain.next_outcome()
                    if outcome.module is BrainIntegrationModule.SPEECH_SEMANTICS:
                        return outcome

            second = await asyncio.wait_for(next_prepared(), 3)
            assert second.status.value == "completed"
            assert (await runtime.candidate(first_id)).lifecycle is CandidateLifecycle.PRESENTING

            async def both_started() -> None:
                while len(notifications) < 2:
                    await asyncio.sleep(0.005)

            await asyncio.wait_for(both_started(), 3)
            before = attention.snapshot()
            await cognition.speech.close()
            assert tasks.pending_task_count == supervisor.active_execution_count == 0
            assert len(notifications) == 4
            assert [a.event.envelope.payload["content"]["status"] for a in notifications].count(
                "cancelled"
            ) == 2
            assert attention.snapshot().current_turn_owner == before.current_turn_owner
            assert attention.snapshot().response_obligation == before.response_obligation
            return

        async def finished() -> None:
            while tasks.pending_task_count:
                await asyncio.sleep(0.005)

        await asyncio.wait_for(finished(), 5)
        await feedback.publish()
        assert len(notifications) == 2
        assert all(a.event.modality is InputModality.SUBSYSTEM for a in notifications)
        assert attention.snapshot().current_turn_owner is None
        assert attention.snapshot().response_obligation is None
        assert supervisor.active_execution_count == 0
        outcomes = []
        for _ in range(3):
            o = await asyncio.wait_for(brain.next_outcome(), 3)
            outcomes.append(o)
        assert any(
            o.module is BrainIntegrationModule.APPRAISAL and o.status.value == "completed"
            for o in outcomes
        )
        assert any(
            o.module is BrainIntegrationModule.EXECUTIVE and o.status.value == "completed"
            for o in outcomes
        )
        assert all(r.role_id != "input_meaning" for r in cognitive_port.requests)
        assert cognition.attention is not None

    finally:
        await brain.stop()
        assert cognition.speech is not None
        await cognition.speech.close()
        assert (
            tasks.pending_task_count
            == supervisor.active_execution_count
            == pipeline.admission.active_count
            == 0
        )
