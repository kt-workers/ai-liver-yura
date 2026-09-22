"""背景振り返りから実DB・判断根拠までの本番接続を検証する。"""

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from app.composition.memory_evidence import (
    CoreMemoryEvidenceConfiguration,
    CoreMemoryEvidenceReader,
)
from app.composition.memory_persistence import CoreMemoryPersistenceBinding
from app.composition.reflection import CoreReflectionConfiguration, CoreReflectionDelivery
from app.domain.activity_execution import ActivityExecutionAuthority
from app.domain.brain_integration import (
    BrainIntegrationLane,
    BrainIntegrationModule,
    BrainIntegrationRuntime,
    BrainWorkStatus,
)
from app.domain.contracts.semantic_subject import SemanticSubjectKind
from app.domain.llm import LLMRoleRequest, LLMRoleResult
from app.domain.memory_reflection import ReflectionAcceptancePolicy, ReflectionCandidateStatus
from app.domain.memory_reflection.llm_roles import proposal_to_wire_v3
from app.infrastructure.persistence import PostgresEndpoint
from app.runtime.kernel import FakeRuntimeClock
from tests.domain.brain_integration.test_runtime import FakePort, envelope, policy, work
from tests.domain.memory import test_memory_store_retrieval as memory
from tests.domain.memory_reflection.test_llm_roles import RolePort, role_policy, support_wire
from tests.domain.memory_reflection.test_memory_reflection import NOW
from tests.domain.memory_reflection.test_subject_supply import typed_pair
from tests.infrastructure.postgresql.test_persistent_boot import boot_config  # noqa: F401
from tests.infrastructure.postgresql.test_runtime import runtime


class DelayedPort(RolePort):
    def __init__(self, *, reject: bool = False) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.reject = reject

    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
        context, proposed = typed_pair(SemanticSubjectKind.REFERENCE)
        if request.role_id == "memory_reflection":
            self.entered.set()
            await self.release.wait()
            self.output = {"proposals": [proposal_to_wire_v3(proposed)]}
        else:
            self.output = support_wire()
            if self.reject:
                self.output["support_relation"] = "ambiguous"
        return await super().invoke(request)


@pytest.mark.asyncio
@pytest.mark.parametrize("reject", [False, True])
async def test_background_store_and_current_memory_evidence(
    endpoint: PostgresEndpoint, reject: bool,
) -> None:
    persistence = runtime(endpoint)
    binding = CoreMemoryPersistenceBinding(persistence, max_pending=4)
    brain = BrainIntegrationRuntime(FakeRuntimeClock(NOW), policy())
    role = DelayedPort(reject=reject)
    delivery = CoreReflectionDelivery(
        brain, binding, ActivityExecutionAuthority(), role, FakeRuntimeClock(NOW),
        CoreReflectionConfiguration(role_policy(), ReflectionAcceptancePolicy("accept", 1), 4),
    )
    brain.register_module(BrainIntegrationModule.INPUT_MEANING, FakePort("前景完了"))
    context, proposed = typed_pair(SemanticSubjectKind.REFERENCE)
    source = context.primary_sources[0]
    try:
        assert await persistence.start() is None
        await brain.start()
        accepted = delivery.submit(envelope(), source, lambda: source)
        assert accepted.accepted
        assert delivery.submit(envelope(), source, lambda: source) == accepted
        await asyncio.wait_for(role.entered.wait(), 2)
        front = work("foreground", BrainIntegrationModule.INPUT_MEANING,
                     BrainIntegrationLane.FOREGROUND_INTERACTION)
        assert brain.submit(front).accepted
        outcome = await asyncio.wait_for(brain.next_outcome(), 2)
        assert outcome.work_id == "foreground" and outcome.result == "前景完了"
        role.release.set()
        completed = await asyncio.wait_for(brain.next_outcome(), 3)
        assert completed.status is BrainWorkStatus.COMPLETED
        operation = delivery.latest_operation
        assert operation is not None and operation.result is not None
        expected = (ReflectionCandidateStatus.REJECTED_AMBIGUOUS if reject
                    else ReflectionCandidateStatus.ACCEPTED_FOR_STORE_SUBMISSION)
        assert operation.result.results[0].status is expected
        found = await binding.submit_retrieval(memory.query()).wait()
        assert found.value is not None
        assert len(found.value.items) == (0 if reject else 1)
        if not reject:
            assert operation.writes[0].result().failure_code is None
            assert found.value.items[0].content == proposed.content
            reader = CoreMemoryEvidenceReader(binding, CoreMemoryEvidenceConfiguration(
                lambda _: memory.query(), 8, 512,
            ))
            # この検索供給元は選択元へ依存しない明示方針。
            facts, tokens = await reader.read(None)  # type: ignore[arg-type]
            assert len(facts) == 1 and tokens
            assert facts[0].fact_id == found.value.items[0].memory_id
            assert reader.latest_entries[0].assertion is not None
    finally:
        role.release.set()
        await brain.stop()
        await delivery.close()
        await binding.close()
        await persistence.close()
    assert binding.pending_count == 0 and persistence.pending_task_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["cancel", "stale", "shutdown"])
async def test_stale_cancel_and_shutdown_do_not_store(
    endpoint: PostgresEndpoint, mode: str,
) -> None:
    persistence = runtime(endpoint)
    binding = CoreMemoryPersistenceBinding(persistence, max_pending=2)
    brain = BrainIntegrationRuntime(FakeRuntimeClock(NOW), policy())
    role = DelayedPort()
    delivery = CoreReflectionDelivery(
        brain, binding, ActivityExecutionAuthority(), role, FakeRuntimeClock(NOW),
        CoreReflectionConfiguration(role_policy(), ReflectionAcceptancePolicy("accept", 1), 2),
    )
    context, _ = typed_pair(SemanticSubjectKind.REFERENCE)
    current = context.primary_sources[0]
    try:
        assert await persistence.start() is None
        await brain.start()
        assert delivery.submit(envelope(), current, lambda: current).accepted
        await asyncio.wait_for(role.entered.wait(), 2)
        operation = delivery.latest_operation
        assert operation is not None
        if mode == "cancel":
            brain.cancel(operation.context.reflection_id, "試験取消")
            brain.cancel(operation.context.reflection_id, "再取消")
        elif mode == "stale":
            current = replace(current, source_revision=(current.source_revision or 0) + 1)
            role.release.set()
        else:
            await brain.stop()
        if mode != "shutdown":
            outcome = await asyncio.wait_for(brain.next_outcome(), 2)
            assert outcome.status is not BrainWorkStatus.RUNNING
        assert operation.writes == ()
        result = await binding.submit_retrieval(memory.query()).wait()
        assert result.value is not None and result.value.items == ()
    finally:
        role.release.set()
        await brain.stop()
        await delivery.close()
        await binding.close()
        await persistence.close()


@pytest.mark.asyncio
async def test_query_bound_is_checked_before_io(endpoint: PostgresEndpoint) -> None:
    persistence = runtime(endpoint)
    binding = CoreMemoryPersistenceBinding(persistence, max_pending=1)
    reader = CoreMemoryEvidenceReader(binding, CoreMemoryEvidenceConfiguration(
        lambda _: memory.query(), 1, 1,
    ))
    try:
        with pytest.raises(ValueError, match="上限"):
            await reader.read(None)  # type: ignore[arg-type]
        assert binding.pending_count == 0
    finally:
        await binding.close()
        await persistence.close()


@pytest.mark.asyncio
async def test_public_boot_registers_roles_and_feeds_memory_into_executive(
    endpoint: PostgresEndpoint, boot_config: Path, monkeypatch: pytest.MonkeyPatch,  # noqa: F811
) -> None:
    from app import bootstrap
    from app.composition.cognition_configuration import CoreCognitionConfiguration
    from app.domain.appraisal import InternalStateReducer
    from app.domain.attention import AttentionSchedulingPolicy, AttentionTurnStore
    from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY as BOUNDS
    from app.domain.contracts import SemanticSubjectIdentity
    from app.domain.contracts.preconditions import PreconditionSourceRouter
    from app.domain.executive import ExecutiveIntentRequirementsPolicy, ExecutiveRequirementsOwner
    from app.domain.memory import MemoryWriteRequest
    from app.domain.plugin_registry import PluginRegistryAuthority
    from tests.domain.appraisal.test_appraisal_paths import policy as appraisal_policy
    from tests.domain.appraisal.test_appraisal_paths import state
    from tests.domain.executive.test_executive import policy as executive_policy
    from tests.domain.memory.test_semantic_assertions import SEMANTICS
    from tests.runtime.test_lifecycle import retry_policy
    from tests.system_integration.test_core_cognition import Port, admission

    port = Port()
    registered: list[str] = []

    from app.domain.llm import LLMRoleDescriptor

    def provider(roles: tuple[LLMRoleDescriptor, ...]) -> Port:
        registered.extend(r.role_id for r in roles)
        return port

    monkeypatch.setattr(bootstrap, "create_openai_port_from_environment", provider)
    requirements = ExecutiveRequirementsOwner(BOUNDS)
    requirements.publish(ExecutiveIntentRequirementsPolicy("wait", 1, ()))
    config = CoreCognitionConfiguration(
        appraisal_policy(), executive_policy(),
        InternalStateReducer(replace(state(), source_context_revision=0)),
        AttentionTurnStore(AttentionSchedulingPolicy.production()), requirements,
        PluginRegistryAuthority(), PreconditionSourceRouter(()), (), (),
        reflection=CoreReflectionConfiguration(
            role_policy(), ReflectionAcceptancePolicy("accept", 1), 4,
        ),
        memory_evidence=CoreMemoryEvidenceConfiguration(lambda _: memory.query(), 8, 512),
    )
    app = await bootstrap.build_persistent_core(
        boot_config, persistence=runtime(endpoint),
        retry_policy=retry_policy("db", retry_enabled=False), runtime_epoch="reflection-test",
        max_pending_memory=4, cognition=config,
    )
    try:
        assert {"memory_reflection", "memory_reflection_support"} <= set(registered)
        assert app.memory is not None and app.cognition is not None
        assert app.cognition.reflection is not None
        assert app.cognition.reflection.activities is app.activities
        candidate = replace(
            memory.candidate(), assertion_semantics=SEMANTICS,
            subject_identity=SemanticSubjectIdentity(SemanticSubjectKind.REFERENCE, "user:1"),
        )
        saved = await app.memory.submit_write(MemoryWriteRequest(candidate)).wait()
        assert saved.value is not None and saved.value.record is not None
        initial_goals = app.goals.snapshot()
        await app.start()
        assert app.cognition.submit_input(admission(app, internal=True)).accepted
        for _ in range(2):
            outcome = await asyncio.wait_for(app.brain.next_outcome(), 3)
            assert outcome.status is BrainWorkStatus.COMPLETED, outcome
        executive = next(r for r in port.requests if r.role_id == "executive_deliberation")
        assert saved.value.record.memory_id in str(executive.input.value)
        assert "memory_evidence" in str(executive.input.value)
        assert app.goals.snapshot() == initial_goals
    finally:
        await app.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["activity", "presentation"])
async def test_actual_owner_terminal_reaches_background_role(
    endpoint: PostgresEndpoint, kind: str,
) -> None:
    from datetime import timedelta

    from app.composition.execution_observation import (
        SPEECH_OBSERVATION_POLICY,
        project_speech_execution_observation,
    )
    from app.domain.activity_execution import ExecutionAdapterReport
    from app.domain.contracts import ExecutionStatus
    from app.domain.speech_runtime.contracts import SpeechPresentationReportStatus
    from tests.domain.activity_execution.test_activity_execution import DISPATCH_ID, started
    from tests.domain.activity_execution.test_activity_execution import NOW as ACTIVITY_NOW
    from tests.system_integration.test_execution_observation_boundary import (
        PROVENANCE,
        presentation,
    )

    class ZeroPort(RolePort):
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            self.output = {"proposals": []}
            result = await super().invoke(request)
            return replace(result, started_at=request.created_at, completed_at=request.created_at)

    persistence = runtime(endpoint)
    binding = CoreMemoryPersistenceBinding(persistence, max_pending=2)
    brain = BrainIntegrationRuntime(FakeRuntimeClock(NOW), policy())
    owner = ActivityExecutionAuthority(observation_policy=SPEECH_OBSERVATION_POLICY)
    role = ZeroPort()
    delivery = CoreReflectionDelivery(
        brain, binding, owner, role, FakeRuntimeClock(NOW),
        CoreReflectionConfiguration(role_policy(), ReflectionAcceptancePolicy("accept", 1), 2),
    )
    try:
        assert await persistence.start() is None
        await brain.start()
        if kind == "activity":
            started(owner)
            terminal = owner.apply_report(ExecutionAdapterReport(
                "command-1", "invocation-command-1", DISPATCH_ID, ExecutionStatus.COMPLETED,
                ACTIVITY_NOW + timedelta(seconds=3), {"code": "completed"},
            ))
            delivery.observe_activity(
                work("parent", BrainIntegrationModule.ACTIVITY_EXECUTION,
                     BrainIntegrationLane.COGNITIVE_NORMAL), terminal.record,
            )
        else:
            speech, command, report = await presentation()
            await speech.accept_report(report)
            initial = await project_speech_execution_observation(
                speech, command.presentation_id, PROVENANCE,
            )
            assert initial is not None
            owner.ingest_observation(initial, policy_id=SPEECH_OBSERVATION_POLICY.policy_id,
                                     policy_revision=SPEECH_OBSERVATION_POLICY.policy_revision)
            assert report.started_at is not None
            await speech.accept_report(replace(
                report, status=SpeechPresentationReportStatus.COMPLETED,
                completed_at=report.started_at + timedelta(seconds=1),
            ))
            final = await project_speech_execution_observation(
                speech, command.presentation_id, PROVENANCE,
            )
            assert final is not None
            observed = owner.ingest_observation(
                final, policy_id=SPEECH_OBSERVATION_POLICY.policy_id,
                policy_revision=SPEECH_OBSERVATION_POLICY.policy_revision,
            )
            delivery.observe_presentation(envelope(), observed)
        assert delivery.last_error is None
        assert delivery.latest_admission is not None and delivery.latest_admission.accepted
        result = await asyncio.wait_for(brain.next_outcome(), 3)
        assert result.status is BrainWorkStatus.COMPLETED, result
        operation = delivery.latest_operation
        assert operation is not None and operation.result is not None
        assert operation.result.results == () and operation.writes == ()
        assert len(role.requests) == 1
        payload = str(role.requests[0].input.value)
        assert "completed" in payload and "effect_uncertainty" in payload
        assert "subject_identity" in payload
    finally:
        await brain.stop()
        await delivery.close()
        await binding.close()
        await persistence.close()


@pytest.mark.asyncio
async def test_storage_failure_and_prestart_cancel_remain_observable(
    endpoint: PostgresEndpoint,
) -> None:
    persistence = runtime(endpoint)
    binding = CoreMemoryPersistenceBinding(persistence, max_pending=2)
    brain = BrainIntegrationRuntime(FakeRuntimeClock(NOW), policy())
    role = DelayedPort()
    role.release.set()
    delivery = CoreReflectionDelivery(
        brain, binding, ActivityExecutionAuthority(), role, FakeRuntimeClock(NOW),
        CoreReflectionConfiguration(role_policy(), ReflectionAcceptancePolicy("accept", 1), 1),
    )
    context, _ = typed_pair(SemanticSubjectKind.REFERENCE)
    source = context.primary_sources[0]
    try:
        await brain.start()
        # DB未起動のUNAVAILABLEを、保存成功へ置き換えない。
        assert delivery.submit(envelope(), source, lambda: source).accepted
        outcome = await asyncio.wait_for(brain.next_outcome(), 2)
        assert outcome.status is BrainWorkStatus.FAILED
        operation = delivery.latest_operation
        assert operation is not None and len(operation.writes) == 1
        assert operation.writes[0].result().failure_code is not None
        newer = replace(source, source_revision=(source.source_revision or 0) + 1)
        assert delivery.submit(envelope(), newer, lambda: newer).accepted
        pending = delivery.latest_operation
        assert pending is not None
        assert brain.cancel(pending.context.reflection_id, "開始前取消")
        cancelled = await asyncio.wait_for(brain.next_outcome(), 2)
        assert cancelled.status is BrainWorkStatus.CANCELLED
        newest = replace(newer, source_revision=(newer.source_revision or 0) + 1)
        # 上限1でも、開始前取消後は新規受付できる。
        assert delivery.submit(envelope(), newest, lambda: newest).accepted
        await asyncio.wait_for(brain.next_outcome(), 2)
    finally:
        await brain.stop()
        await delivery.close()
        await binding.close()
        await persistence.close()
