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
from app.config.minimum_brain import load_minimum_brain_config
from app.domain.brain_integration import BrainIntegrationModule, BrainWorkStatus
from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY as BOUNDS
from app.domain.contracts import CapabilityAvailability, RevisionVector
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
from app.subsystems.validation.body import _project
from app.subsystems.validation.cognition import NormalCognitionLabCase, normal_cognition_target
from app.subsystems.validation.contracts import Gate, LabMode, RunStatus
from app.subsystems.validation.provenance import capture_production_provenance
from app.subsystems.validation.runtime import ValidationRunner
from tests.domain.goals.test_goal_commitment_store import apply_goal
from tests.infrastructure.postgresql.test_brain_nonserial_acceptance import assert_reaped
from tests.subsystems.validation.test_runtime import FIXTURE, POLICY, spec
from tests.system_integration.test_core_cognition import Port
from tests.system_integration.test_core_cognition_hardening import configuration

ROOT = Path(__file__).resolve().parents[2]


class SystemRun:
    """意味を生成せず、本番入口・外部提供先・観測記録を同一起動へ結び付ける。"""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.provider = Port()
        self.roles: list[LLMRoleDescriptor] = []

        def provider(roles: Any) -> Port:
            self.roles.extend(roles)
            return self.provider

        monkeypatch.setattr(bootstrap, "create_openai_port_from_environment", provider)
        self.registration = configuration()
        self.app = bootstrap.build_minimum_core(cognition=self.registration)
        self.normalizer = InputNormalizer(InputAdmissionLedger(), bounds_policy=BOUNDS)
        self.run_id = str(uuid4())
        self.observed: list[Any] = []
        self.provenance = self.current_provenance()
        loaded = load_minimum_brain_config(
            (ROOT / "resources/config/v2/minimum_brain.yaml").read_bytes()
        )
        assert self.app.config == loaded
        assert {r.role_id for r in self.roles} == {
            "input_meaning",
            "subjective_appraisal",
            "executive_deliberation",
        }
        assert self.app.runtime_subject_identity.character_definition_revision == (
            self.app.character_definition.definition_revision
        )

    def current_provenance(self) -> Any:
        return replace(
            capture_production_provenance(
                ROOT,
                (
                    "app",
                    "resources/config/v2/minimum_brain.yaml",
                    self.app.config.character_definition_path,
                ),
                ("system_integration_contracts.md", "brain_integration_contracts.md"),
                tuple(r.output_schema_id for r in self.roles),
            ),
            character_definition_revision=str(self.app.character_definition.definition_revision),
            provider_config_revision=f"deterministic-provider:{self.app.config.config_revision}",
            runtime_policy_revision=str(self.app.config.integration_policy.policy_revision),
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
        await self.app.stop()
        await self.app.stop()
        assert_reaped(self.app)


@pytest.mark.asyncio
@pytest.mark.parametrize("internal", [False, True])
async def test_system_configuration_and_lab_evidence_reach_owner_decision(
    monkeypatch: pytest.MonkeyPatch,
    internal: bool,
) -> None:
    run = SystemRun(monkeypatch)
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
    run = SystemRun(monkeypatch)
    invoke = run.provider.invoke

    async def controlled(request: LLMRoleRequest) -> LLMRoleResult:
        if request.trace_id == "failed" and request.role_id == role:
            return await UnavailableLLMRolePort(tuple(run.roles)).invoke(request)
        return await invoke(request)

    monkeypatch.setattr(run.provider, "invoke", controlled)
    assert run.app.cognition is not None
    await run.app.start()
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
    run = SystemRun(monkeypatch)
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
    await run.app.start()
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
                await run.stop()
                with pytest.raises(RuntimeError, match="受付"):
                    run.app.cognition.submit_input(run.input("late"))
            terminal = [await run.outcome() for _ in range(2)]
            assert {o.trace_id for o in terminal} == {"A", "B"}
            assert all(
                o.status
                is (BrainWorkStatus.FAILED if operation == "stale" else BrainWorkStatus.CANCELLED)
                for o in terminal
            )
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
