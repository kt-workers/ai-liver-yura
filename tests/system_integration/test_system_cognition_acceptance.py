"""同じ本番構成の公開認知結果を、設定来歴付きSystem証拠として検証する。"""

import asyncio
import json
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from app import bootstrap
from app.adapters.llm.production import UnavailableLLMRolePort
from app.composition.s2_provider import S2ProviderLease
from app.composition.system_cognition_configuration import (
    S2ProductionApplication,
    S2RunIdentity,
    current_artifact_head,
)
from app.config.cognition_s2 import load_s2_config
from app.config.minimum_brain import load_minimum_brain_config
from app.domain.brain_integration import BrainIntegrationModule, BrainWorkStatus
from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY as BOUNDS
from app.domain.contracts import CapabilityAvailability, RevisionVector
from app.domain.contracts.finalization import FinalizationError, FinalizationFailure
from app.domain.contracts.preconditions import PreconditionSourceRouter
from app.domain.executive import GoalTransitionOperation
from app.domain.goals import GoalCommitmentStore
from app.domain.input_gateway import (
    InputAdmissionLedger,
    InputModality,
    InputNormalizer,
    InputObservation,
    InputPermission,
    InputSourceState,
)
from app.domain.llm import LLMFailureCode, LLMRoleDescriptor, LLMRoleRequest, LLMRoleResult
from app.domain.plugin_registry import PluginRegistryAuthority
from app.runtime.kernel import SystemRuntimeClock
from app.subsystems.validation.body import _project
from app.subsystems.validation.cognition import NormalCognitionLabCase, normal_cognition_target
from app.subsystems.validation.contracts import Gate, LabMode, RunStatus
from app.subsystems.validation.provenance import capture_production_provenance
from app.subsystems.validation.runtime import ValidationRunner
from tests.domain.goals.test_goal_commitment_store import apply_goal
from tests.infrastructure.postgresql.test_brain_nonserial_acceptance import assert_reaped
from tests.subsystems.validation.test_runtime import FIXTURE, POLICY, spec
from tests.system_integration.test_core_cognition import Port

ROOT = Path(__file__).resolve().parents[2]


class SystemRun:
    """意味を生成せず、本番入口・外部提供先・観測記録を同一起動へ結び付ける。"""

    @classmethod
    async def create(cls) -> "SystemRun":
        provider = Port()
        registered_roles: list[LLMRoleDescriptor] = []
        leases: list[S2ProviderLease] = []
        releases: list[str] = []

        async def factory(roles: Any, configs: Any, bindings: Any, mode: str) -> S2ProviderLease:
            registered_roles.extend(roles)
            # 採用済み未設定manifestを保持し、外部I/Oだけを置換する。
            assert not configs and mode == "unconfigured"

            async def release() -> None:
                releases.append("provider")

            lease = S2ProviderLease(provider, bindings, mode, release)
            leases.append(lease)
            return lease

        identity = S2RunIdentity(current_artifact_head(), str(uuid4()), str(uuid4()))
        s2 = await bootstrap.build_s2_production_core(
            run_identity=identity,
            activation_id="yura.cognition-s2.explicit",
            fresh_start=True,
            clock=SystemRuntimeClock(),
            registry=PluginRegistryAuthority(),
            precondition_router=PreconditionSourceRouter(()),
            precondition_bindings=(),
            activity_bindings={},
            fast_rules=(),
            provider_source=None,
            provider_factory=factory,
        )
        return cls(s2, provider, registered_roles, leases, releases, identity)

    def __init__(
        self,
        s2: S2ProductionApplication,
        provider: Port,
        roles: list[LLMRoleDescriptor],
        leases: list[S2ProviderLease],
        releases: list[str],
        identity: S2RunIdentity,
    ) -> None:
        self.s2 = s2
        self.app: Any = s2.core
        self.provider = provider
        self.roles = roles
        self.leases = leases
        self.releases = releases
        self.registration = s2.cognition
        self.normalizer = InputNormalizer(InputAdmissionLedger(), bounds_policy=BOUNDS)
        self.run_id = identity.system_run_id
        self.observed: list[Any] = []
        self.snapshot = s2.composition_snapshot
        self.provenance = self.current_provenance()
        config = load_s2_config((ROOT / "resources/config/v2/cognition_s2.yaml").read_bytes())
        loaded = load_minimum_brain_config((ROOT / config.minimum_config.resource_ref).read_bytes())
        assert self.app.config == loaded
        snapshot = self.snapshot
        assert (snapshot.config_id, snapshot.config_revision) == (
            config.config_id,
            config.config_revision,
        )
        assert (snapshot.composition_id, snapshot.composition_revision) == (
            config.composition_id,
            config.composition_revision,
        )
        assert snapshot.activation_id == config.activation_id
        assert (snapshot.git_head, snapshot.runtime_epoch, snapshot.system_run_id) == (
            current_artifact_head(),
            identity.runtime_epoch,
            self.run_id,
        )
        assert (snapshot.character_id, snapshot.character_definition_revision) == (
            self.app.character_definition.character_id,
            self.app.character_definition.definition_revision,
        )
        (component,) = snapshot.component_bindings
        assert (component.minimum_config_id, component.minimum_config_revision) == (
            loaded.config_id,
            loaded.config_revision,
        )
        assert component.appraisal == s2.appraisal.provenance
        assert component.executive == s2.executive.provenance
        assert component.appraisal.runtime_epoch == identity.runtime_epoch
        assert component.appraisal.source_context_revision == (
            self.app.input_context.snapshot().context.source_context_revision
        )
        assert (component.attention_policy_id, component.attention_policy_revision) == (
            config.attention_policy.policy_id,
            config.attention_policy.policy_revision,
        )
        attention = self.registration.attention.snapshot()
        assert (attention.policy_id, attention.policy_revision) == (
            component.attention_policy_id,
            component.attention_policy_revision,
        )
        requirements = s2.executive.initial_generation.policy
        assert requirements == s2.executive.config.requirements
        assert (requirements.policy_id, requirements.revision) == (
            component.executive.requirements_policy_id,
            component.executive.requirements_policy_revision,
        )
        assert component.executive.source_config_ref == config.executive_config.resource_ref
        assert component.appraisal.source_config_ref == config.appraisal_config.resource_ref
        assert snapshot.requirements_generation == component.executive.initial_generation_identity
        assert self.registration.requirements is s2.executive.requirements_owner
        assert (
            self.registration.requirements.current_generation() is s2.executive.initial_generation
        )
        assert (
            s2.executive.initial_generation.serial == component.executive.initial_generation_serial
        )
        assert len(leases) == 1 and snapshot.provider_bindings == leases[0].bindings
        registered = {r.role_id: r for r in roles}
        assert set(registered) == {
            "input_meaning",
            "subjective_appraisal",
            "executive_deliberation",
        }
        for binding in snapshot.provider_bindings:
            descriptor = registered[binding.role_id]
            assert binding.input_schema_id == descriptor.input_schema_id
            assert binding.output_schema_id == descriptor.output_schema_id
            assert (binding.deployment_id, binding.deployment_revision) == (
                config.provider_deployment.deployment_id,
                config.provider_deployment.deployment_revision,
            )
            assert binding.availability_mode == "unconfigured"
        assert registered["subjective_appraisal"].default_execution_policy == (
            self.registration.appraisal_policy.execution
        )
        assert registered["executive_deliberation"].default_execution_policy == (
            self.registration.executive_policy.execution
        )
        for role, provenance in (
            ("subjective_appraisal", component.appraisal),
            ("executive_deliberation", component.executive),
        ):
            policy = registered[role].default_execution_policy
            assert (policy.policy_id, policy.policy_revision) == (
                provenance.execution_policy_id,
                provenance.execution_policy_revision,
            )
        assert "test.llm.execution" not in json.dumps(asdict(snapshot), default=str)
        assert all(r.default_execution_policy.policy_id != "test.llm.execution" for r in roles)
        assert self.app.runtime_subject_identity.character_definition_revision == (
            snapshot.character_definition_revision
        )

    def current_provenance(self) -> Any:
        snapshot = self.s2.composition_snapshot
        assert snapshot is self.snapshot
        assert snapshot.git_head == current_artifact_head()
        provenance = capture_production_provenance(
            ROOT,
            ("app", "resources/config/v2", self.app.config.character_definition_path),
            (
                "system_integration_contracts.md",
                "brain_integration_contracts.md",
                "system_production_cognition_configuration.md",
            ),
            tuple(r.output_schema_id for r in self.roles),
        )
        assert provenance.git_head == snapshot.git_head
        # Labの既存INTEGRATED形式へ、同一runのSnapshot由来だけを投影する。
        providers = ",".join(
            f"{b.role_id}:{b.deployment_id}:{b.deployment_revision}:{b.availability_mode}"
            for b in snapshot.provider_bindings
        )
        return replace(
            provenance,
            character_definition_revision=str(snapshot.character_definition_revision),
            provider_config_revision=providers,
            runtime_policy_revision=f"{snapshot.composition_id}:{snapshot.composition_revision}",
        )

    def input(self, key: str, *, internal: bool = False) -> Any:
        return self.normalizer.normalize(
            InputObservation(
                key,
                InputSourceState(
                    "system-source",
                    "system" if internal else "user",
                    CapabilityAvailability.AVAILABLE,
                    InputPermission.GRANTED,
                ),
                InputModality.SUBSYSTEM if internal else InputModality.TEXT,
                "completed" if internal else "utterance",
                datetime.now(timezone.utc),
                key,
                RevisionVector(self.app.input_context.snapshot().context.source_context_revision),
                {"activity_ref": key} if internal else {"text": "こんにちは"},
            )
        )

    async def outcome(self) -> Any:
        item = await asyncio.wait_for(self.app.brain.next_outcome(), 3)
        assert item.work_id not in {o.work_id for o in self.observed}
        self.observed.append(item)
        return item

    def evidence(self, *keys: str) -> Any:
        assert self.current_provenance() == self.provenance
        value = _project(
            {
                "run_id": self.run_id,
                "provenance": asdict(self.provenance),
                "composition_snapshot": asdict(self.snapshot),
                "configuration": {
                    "config_id": self.app.config.config_id,
                    "config_revision": self.app.config.config_revision,
                    "scheduler": asdict(self.app.config.scheduler_policy),
                    "integration": asdict(self.app.config.integration_policy),
                },
                "roles": tuple(r.to_dict() for r in self.roles),
                "traces": tuple(self.app.brain.trace(key) for key in keys),
                "terminal": tuple(
                    (o.work_id, o.trace_id, o.module, o.status) for o in self.observed
                ),
            }
        )
        return json.loads(json.dumps(value, default=lambda v: dict(v)))

    async def stop(self) -> None:
        await self.s2.stop()
        await self.s2.stop()
        assert_reaped(self.app)
        assert self.releases == ["provider"]
        for owner in (
            self.registration.attention,
            self.registration.requirements,
            self.app.goals,
            self.app.activities,
        ):
            with pytest.raises(FinalizationError) as failure:
                owner.finalization_participant.token()
            assert failure.value.failure is FinalizationFailure.PARTICIPANT_UNAVAILABLE
        assert self.s2.composition_snapshot is self.snapshot


@pytest.mark.asyncio
@pytest.mark.parametrize("internal", [False, True])
async def test_system_configuration_and_lab_evidence_reach_owner_decision(
    internal: bool,
) -> None:
    run = await SystemRun.create()
    accepted = run.input("internal" if internal else "user", internal=internal)
    assert accepted.event is not None
    fixture = replace(FIXTURE, typed_inputs=_project(accepted))
    target = normal_cognition_target(
        (NormalCognitionLabCase(fixture, accepted),),
        lambda: run.app,
        run.provenance,
        "1",
        (),
        provenance_source=run.current_provenance,
    )
    runner = ValidationRunner((target,), replace(POLICY, timeout_seconds=3, max_intervals=100))
    request = replace(
        spec(), run_id=run.run_id, mode=LabMode.INTEGRATED, target_module="normal_cognition"
    )
    before = asyncio.all_tasks()
    try:
        result = await runner.run(request, fixture)
        assert result.status is RunStatus.COMPLETED and result.machine_gate is Gate.PASS
        exported = json.loads(result.export_json(1_000_000))
        assert exported["human_evaluation"]["status"] == "UNRATED"
        assert exported["target_provenance"]["git_head"] == run.provenance.git_head
        assert exported["run_spec"]["run_id"] == run.run_id
        value: Any = result.stage_results[0].typed_outputs
        modules = [o["module"] for o in value["outcomes"]]
        assert modules == (
            ["appraisal", "executive"] if internal else ["input_meaning", "appraisal", "executive"]
        )
        event = accepted.event.envelope
        assert value["trace"]["root_trigger_id"] == event.event_id
        assert value["trace"]["source_event_ids"] == (event.event_id,)
        candidate = value["outcomes"][-1]["result"]["candidate"]
        assert candidate["source_event_ids"] == (event.event_id,)
        decision_request = run.provider.requests[-1]
        assert decision_request.role_id == "executive_deliberation"
        assert decision_request.trace_id == event.trace_id
        assert candidate["source_context_revision"] == event.revisions.source_context_revision
        assert candidate["goal_revision"] == run.app.goals.snapshot().revision
        assert candidate["attention_revision"] == decision_request.revisions.attention_revision
        assert candidate["trigger_id"] != event.event_id
        executive_interval = value["trace"]["intervals"][-1]
        assert executive_interval["goal_revision"] == candidate["goal_revision"]
        assert executive_interval["attention_revision"] == candidate["attention_revision"]
        assert executive_interval["source_context_revision"] == candidate["source_context_revision"]
        assert run.registration.attention.snapshot().sources
        assert [r.role_id for r in run.provider.requests] == (
            ["subjective_appraisal", "executive_deliberation"]
            if internal
            else ["input_meaning", "subjective_appraisal", "executive_deliberation"]
        )
        evidence = run.evidence(event.trace_id)
        assert evidence["traces"][0]["trace_id"] == value["trace"]["trace_id"]
        assert evidence["configuration"]["config_revision"] == run.app.config.config_revision
        assert result.target_provenance == run.provenance
        assert (
            evidence["composition_snapshot"]["git_head"]
            == exported["target_provenance"]["git_head"]
        )
        assert evidence["composition_snapshot"]["system_run_id"] == exported["run_spec"]["run_id"]
        registered = {r.role_id: r for r in run.roles}
        for request_used in run.provider.requests:
            assert (
                request_used.execution_policy
                == registered[request_used.role_id].default_execution_policy
            )
    finally:
        await runner.close()
        await run.stop()
    assert runner.pending_count == 0
    assert not (asyncio.all_tasks() - before)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["input_meaning", "subjective_appraisal"])
async def test_typed_provider_failure_keeps_other_system_trace_available(
    monkeypatch: pytest.MonkeyPatch,
    role: str,
) -> None:
    run = await SystemRun.create()
    invoke = run.provider.invoke

    async def controlled(request: LLMRoleRequest) -> LLMRoleResult:
        if request.trace_id == "failed" and request.role_id == role:
            return await UnavailableLLMRolePort(tuple(run.roles)).invoke(request)
        return await invoke(request)

    monkeypatch.setattr(run.provider, "invoke", controlled)
    assert run.app.cognition is not None
    await run.s2.start()
    try:
        # Meaning失敗は外部入力、Appraisal失敗は内部契機として別境界を検証する。
        # 採用済みUSER sourceの寿命は後続Appraisalの失敗と同一ではない。
        assert run.app.cognition.submit_input(
            run.input("failed", internal=role == "subjective_appraisal")
        ).accepted
        terminal = await run.outcome()
        if role == "input_meaning":
            assert terminal.result.meaning is None
            assert terminal.result.role_failure.code is LLMFailureCode.PROVIDER_UNAVAILABLE
        else:
            assert terminal.status is BrainWorkStatus.FAILED
        assert not any(r.role_id == "executive_deliberation" for r in run.provider.requests)
        assert run.app.cognition.submit_input(run.input("healthy")).accepted
        for _ in range(3):
            healthy = await run.outcome()
            assert healthy.trace_id == "healthy" and healthy.status is BrainWorkStatus.COMPLETED
        assert healthy.module is BrainIntegrationModule.EXECUTIVE
        assert healthy.result.candidate.source_event_ids == ("input:healthy",)
        evidence = run.evidence("failed", "healthy")
        assert not evidence["traces"][0]["activity_ids"]
        assert all(
            o.module is not BrainIntegrationModule.EXECUTIVE
            for o in run.observed
            if o.trace_id == "failed"
        )
    finally:
        await run.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["cancel", "supersede", "stale", "stop"])
async def test_system_consumer_observes_nonserial_rejection_and_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    before = asyncio.all_tasks()
    run = await SystemRun.create()
    entered = {key: asyncio.Event() for key in ("A", "B")}
    release = {key: asyncio.Event() for key in entered}
    invoke = run.provider.invoke

    async def controlled(request: LLMRoleRequest) -> LLMRoleResult:
        if request.role_id == "subjective_appraisal":
            entered[request.trace_id].set()
            await release[request.trace_id].wait()
        return await invoke(request)

    monkeypatch.setattr(run.provider, "invoke", controlled)
    assert run.app.cognition is not None
    await run.s2.start()
    try:
        for key in entered:
            assert run.app.cognition.submit_input(run.input(key)).accepted
            await asyncio.wait_for(entered[key].wait(), 3)
            meaning = await run.outcome()
            assert meaning.module is BrainIntegrationModule.INPUT_MEANING
            assert meaning.trace_id == key and meaning.status is BrainWorkStatus.COMPLETED
        assert not release["A"].is_set()
        if operation in ("cancel", "supersede"):
            assert (
                run.app.cognition.cancel_trace(
                    "A", "System対象取消", supersede=operation == "supersede"
                )
                == 1
            )
            terminal = await run.outcome()
            assert terminal.trace_id == "A"
            assert terminal.status is (
                BrainWorkStatus.CANCELLED if operation == "cancel" else BrainWorkStatus.SUPERSEDED
            )
            release["B"].set()
            for _ in range(2):
                decision = await run.outcome()
                assert decision.trace_id == "B" and decision.status is BrainWorkStatus.COMPLETED
            assert decision.module is BrainIntegrationModule.EXECUTIVE
            assert decision.result.candidate.source_event_ids == ("input:B",)
        else:
            if operation == "stale":
                assert isinstance(run.app.goals, GoalCommitmentStore)
                apply_goal(run.app.goals, GoalTransitionOperation.CREATE, 0)
                for gate in release.values():
                    gate.set()
            else:
                # 停止で参照Ownerも退役するため、受付拒否の入力は停止前に正規生成する。
                late = run.input("late")
                await run.stop()
                with pytest.raises(FinalizationError) as rejected:
                    run.app.cognition.submit_input(late)
                assert rejected.value.failure is FinalizationFailure.PARTICIPANT_UNAVAILABLE
                assert_reaped(run.app)
            terminal = [await run.outcome() for _ in range(2)]
            assert {o.trace_id for o in terminal} == {"A", "B"}
            assert all(
                o.status
                is (BrainWorkStatus.FAILED if operation == "stale" else BrainWorkStatus.CANCELLED)
                for o in terminal
            )
            assert run.app.cognition.appraisal.latest_commit() is None
            if operation == "stop":
                with pytest.raises(FinalizationError) as retired:
                    run.app.cognition.appraisal.current_commit()
                assert retired.value.failure is FinalizationFailure.PARTICIPANT_UNAVAILABLE
            else:
                assert run.app.cognition.appraisal.current_commit() is None
        evidence = run.evidence("A", "B")
        for index, key in enumerate(entered):
            trace = evidence["traces"][index]
            assert trace["root_trigger_id"] == f"input:{key}"
            assert trace["source_event_ids"] == [f"input:{key}"]
            if key == "A" or operation in ("stale", "stop"):
                assert not trace["activity_ids"] and not trace["speech_candidate_ids"]
                assert all(
                    o.module is not BrainIntegrationModule.EXECUTIVE
                    for o in run.observed
                    if o.trace_id == key
                )
    finally:
        for gate in release.values():
            gate.set()
        await run.stop()
    assert not (asyncio.all_tasks() - before)
