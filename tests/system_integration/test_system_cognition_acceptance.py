"""同じ本番構成の公開認知結果を、設定来歴付きSystem証拠として検証する。"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from app import application as bootstrap
from app.adapters.llm.production import UnavailableLLMRolePort
from app.bootstrap.system_cognition_configuration import (
    CoreApplication,
    CoreRunIdentity,
)
from app.config.appraisal import load_appraisal_config
from app.config.core import load_core_config
from app.config.executive import load_executive_config
from app.config.llm_connections import LLMConnectionConfig
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
from app.infrastructure.scheduling import SystemRuntimeClock
from app.subsystems.validation.body import _project
from app.subsystems.validation.cognition import NormalCognitionLabCase, normal_cognition_target
from app.subsystems.validation.contracts import Gate, LabMode, RunStatus
from app.subsystems.validation.provenance import capture_production_provenance
from app.subsystems.validation.runtime import ValidationRunner
from app.usecases.ports.llm import LLMRolePort
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
        connections: list[str] = []
        releases: list[str] = []

        class TestConnectionAdapter:
            """実System構成だけを通し、Provider I/Oを検証用Portで差し替える。"""

            adapter_id = "openai_responses"

            async def connect(
                self,
                connection: object,
                descriptors: tuple[LLMRoleDescriptor, ...],
            ) -> tuple[LLMRolePort, Callable[[], Awaitable[None]]]:
                if not isinstance(connection, LLMConnectionConfig):
                    raise ValueError("本番構成のLLM接続契約が不正です")
                connections.append(connection.connection_id)
                registered_roles.extend(descriptors)

                async def release() -> None:
                    releases.append(connection.connection_id)

                return provider, release

        identity = CoreRunIdentity(str(uuid4()), str(uuid4()))
        core = await bootstrap.build_core(
            run_identity=identity,
            activation_id="yura.core.explicit",
            fresh_start=True,
            clock=SystemRuntimeClock(),
            registry=PluginRegistryAuthority(),
            precondition_router=PreconditionSourceRouter(()),
            precondition_bindings=(),
            activity_bindings={},
            fast_rules=(),
            llm_adapters=(TestConnectionAdapter(),),
        )
        return cls(core, provider, registered_roles, connections, releases, identity)

    def __init__(
        self,
        core: CoreApplication,
        provider: Port,
        roles: list[LLMRoleDescriptor],
        connections: list[str],
        releases: list[str],
        identity: CoreRunIdentity,
    ) -> None:
        self.core = core
        self.app: Any = core.core
        self.provider = provider
        self.roles = roles
        self.connections = connections
        self.releases = releases
        self.registration = core.cognition
        self.normalizer = InputNormalizer(InputAdmissionLedger(), bounds_policy=BOUNDS)
        self.run_id = identity.system_run_id
        self.observed: list[Any] = []
        self.returned_outcome_ids: set[str] = set()
        self.snapshot = core.composition_snapshot
        self.provenance = self.current_provenance()
        config = load_core_config((ROOT / "config/core.yaml").read_bytes())
        loaded = config
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
        assert (snapshot.runtime_epoch, snapshot.system_run_id) == (
            identity.runtime_epoch,
            self.run_id,
        )
        assert (snapshot.character_id, snapshot.character_definition_revision) == (
            self.app.character_definition.character_id,
            self.app.character_definition.definition_revision,
        )
        (component,) = snapshot.component_bindings
        assert (component.core_config_id, component.core_config_revision) == (
            loaded.config_id,
            loaded.config_revision,
        )
        assert component.appraisal == core.appraisal.provenance
        assert component.executive == core.executive.provenance
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
        requirements = core.executive.initial_generation.policy
        assert requirements == core.executive.config.requirements
        assert (requirements.policy_id, requirements.revision) == (
            component.executive.requirements_policy_id,
            component.executive.requirements_policy_revision,
        )
        assert component.executive.source_config_ref == config.executive_config.resource_ref
        assert component.appraisal.source_config_ref == config.appraisal_config.resource_ref
        assert snapshot.requirements_generation == component.executive.initial_generation_identity
        assert self.registration.requirements is core.executive.requirements_owner
        assert (
            self.registration.requirements.current_generation() is core.executive.initial_generation
        )
        assert (
            core.executive.initial_generation.serial
            == component.executive.initial_generation_serial
        )
        assert connections == ["yura.llm.default"]
        registered = {r.role_id: r for r in roles}
        assert set(registered) == {
            "input_meaning",
            "subjective_appraisal",
            "executive_deliberation",
        }
        appraisal_config = load_appraisal_config(
            (ROOT / config.appraisal_config.resource_ref).read_bytes()
        )
        executive_config = load_executive_config(
            (ROOT / config.executive_config.resource_ref).read_bytes()
        )
        assert {
            binding.role_id: binding.connection_id
            for binding in snapshot.llm_connection_bindings
        } == {
            "input_meaning": config.input_meaning_llm_connection_id,
            "subjective_appraisal": appraisal_config.llm_connection_id,
            "executive_deliberation": executive_config.llm_connection_id,
        }
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
        snapshot = self.core.composition_snapshot
        assert snapshot is self.snapshot
        provenance = capture_production_provenance(
            ROOT,
            ("app", "config", self.app.config.character_definition.resource_ref),
            (
                "system_integration_contracts.md",
                "brain_integration_contracts.md",
                "system_production_cognition_configuration.md",
            ),
            tuple(r.output_schema_id for r in self.roles),
        )
        # Labの既存INTEGRATED形式へ、同一runのSnapshot由来だけを投影する。
        providers = ",".join(
            f"{binding.role_id}:{binding.connection_id}"
            for binding in snapshot.llm_connection_bindings
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

    async def outcome(
        self,
        trace_id: str | None = None,
        module: BrainIntegrationModule | None = None,
    ) -> Any:
        # 独立laneの完了順は固定しない。別traceの先着結果は観測記録へ保持し、
        # 後続の要求が同じ終端を相関取得できるようにする。
        for item in self.observed:
            if item.work_id not in self.returned_outcome_ids and (
                trace_id is None or item.trace_id == trace_id
            ) and (module is None or item.module is module):
                self.returned_outcome_ids.add(item.work_id)
                return item
        while True:
            item = await asyncio.wait_for(self.app.brain.next_outcome(), 3)
            assert item.work_id not in {o.work_id for o in self.observed}
            self.observed.append(item)
            if (trace_id is None or item.trace_id == trace_id) and (
                module is None or item.module is module
            ):
                self.returned_outcome_ids.add(item.work_id)
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
        await self.core.stop()
        await self.core.stop()
        assert_reaped(self.app)
        assert self.releases == ["yura.llm.default"]
        for owner in (
            self.registration.attention,
            self.registration.requirements,
            self.app.goals,
            self.app.activities,
        ):
            with pytest.raises(FinalizationError) as failure:
                owner.finalization_participant.token()
            assert failure.value.failure is FinalizationFailure.PARTICIPANT_UNAVAILABLE
        assert self.core.composition_snapshot is self.snapshot


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
    await run.core.start()
    try:
        # Meaning失敗は外部入力、Appraisal失敗は内部契機として別境界を検証する。
        # 採用済みUSER sourceの寿命は後続Appraisalの失敗と同一ではない。
        assert run.app.cognition.submit_input(
            run.input("failed", internal=role == "subjective_appraisal")
        ).accepted
        terminal = await run.outcome(
            "failed",
            BrainIntegrationModule.INPUT_MEANING
            if role == "input_meaning"
            else BrainIntegrationModule.APPRAISAL,
        )
        if role == "input_meaning":
            assert terminal.result.meaning is None
            assert terminal.result.role_failure.code is LLMFailureCode.PROVIDER_UNAVAILABLE
        else:
            assert terminal.status is BrainWorkStatus.FAILED
        assert not any(r.role_id == "executive_deliberation" for r in run.provider.requests)
        assert run.app.cognition.submit_input(run.input("healthy")).accepted
        for module in (
            BrainIntegrationModule.INPUT_MEANING,
            BrainIntegrationModule.APPRAISAL,
            BrainIntegrationModule.EXECUTIVE,
        ):
            healthy = await run.outcome("healthy", module)
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
    await run.core.start()
    try:
        for key in entered:
            assert run.app.cognition.submit_input(run.input(key)).accepted
            await asyncio.wait_for(entered[key].wait(), 3)
            meaning = await run.outcome(key, BrainIntegrationModule.INPUT_MEANING)
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
            terminal = await run.outcome("A")
            assert terminal.trace_id == "A"
            assert terminal.status is (
                BrainWorkStatus.CANCELLED if operation == "cancel" else BrainWorkStatus.SUPERSEDED
            )
            release["B"].set()
            for module in (BrainIntegrationModule.APPRAISAL, BrainIntegrationModule.EXECUTIVE):
                decision = await run.outcome("B", module)
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
            terminal = [
                await run.outcome(key, BrainIntegrationModule.APPRAISAL) for key in ("A", "B")
            ]
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
