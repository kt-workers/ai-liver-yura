"""実際の入力採用と所有者読取を通し、判断根拠の由来と失敗を検証する。"""

import asyncio
from collections.abc import Mapping
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app import bootstrap
from app.bootstrap import InputMeaningBrainModulePort, InputMeaningBrainWorkPayload
from app.composition.accepted_input import CoreAcceptedInput, CoreAcceptedInputStore
from app.composition.executive import CoreExecutiveBinding
from app.composition.executive_input_evidence import CoreExecutiveInputEvidenceReader
from app.domain.attention import AttentionSource, AttentionSourceKind
from app.domain.contracts import RevisionVector
from app.domain.contracts.common import freeze_json
from app.domain.contracts.finalization import AuthorityReadPublication
from app.domain.executive import (
    AuthoritativeIntentRequirements,
    ExecutiveContextSnapshot,
    ExecutiveDecisionCandidate,
    GoalTransitionOperation,
    PreconditionFact,
)
from app.domain.input_meaning import InputMeaningFreshnessStamp, InputMeaningInterpreter
from app.domain.llm import LLMRoleRequest, LLMRoleResult
from app.domain.plugin_registry import PluginRegistryAuthority
from app.runtime.kernel import CancellationToken
from tests.domain.executive.test_executive import policy as executive_policy
from tests.domain.goals.test_goal_commitment_store import apply_goal
from tests.domain.input_meaning.test_input_meaning import event, policy
from tests.domain.plugin_registry.test_plugin_registry import grants, manifest
from tests.helpers.executive_requirements import make_authority
from tests.system_integration.test_core_appraisal import Setup, setup
from tests.system_integration.test_core_attention import connect
from tests.system_integration.test_core_executive import Port
from tests.system_integration.test_early_boot import SuccessfulPort, work


class Requirements:
    def __init__(self) -> None:
        self.fail = False
        self.calls = 0

    async def preconditions_for(
        self, source: AttentionSource
    ) -> tuple[AuthorityReadPublication[PreconditionFact], ...]:
        if self.fail:
            raise ValueError("前提条件の供給元が未登録です")
        return ()

    async def requirements_for(
        self, snapshot: ExecutiveContextSnapshot, candidate: ExecutiveDecisionCandidate
    ) -> tuple[AuthoritativeIntentRequirements, ...]:
        self.calls += 1
        if self.fail:
            raise ValueError("必須要件の供給元が未登録です")
        # この試験方針は実行要求を受け付けない。
        if candidate.intents:
            raise ValueError("この試験方針には実行要件が登録されていません")
        return ()


async def wired(*, with_goal: bool = False, core: Setup | None = None) -> Any:
    core = setup() if core is None else core
    if with_goal:
        apply_goal(core.goals, GoalTransitionOperation.CREATE, 0)
    reference = core.connection.current_reference()
    observed = event()
    observed = replace(
        observed,
        envelope=replace(
            observed.envelope,
            event_id="event:1",
            trace_id=core.event.trace_id,
            revisions=RevisionVector(reference.context.source_context_revision),
        ),
    )

    class Live:
        async def current_freshness_stamp(self) -> InputMeaningFreshnessStamp:
            assert core is not None
            return core.connection.current_reference().freshness

    inputs = CoreAcceptedInputStore(2)
    bridge = InputMeaningBrainModulePort(
        InputMeaningInterpreter(SuccessfulPort(), Live(), policy()), inputs
    )
    original = work()
    submitted = replace(
        original,
        envelope=replace(
            original.envelope,
            trace_id=observed.envelope.trace_id,
            source_event_ids=(observed.envelope.event_id,),
            source_context_revision=reference.context.source_context_revision,
        ),
        payload=InputMeaningBrainWorkPayload(observed, reference.context, "input-request"),
    )
    result = await bridge.execute(submitted, CancellationToken())
    assert result.meaning is not None
    core.event, core.meaning = observed.envelope, result.meaning
    await core.appraise()
    attention, _ = connect(core)
    attention.offer_appraisal()
    dispatch = attention.claim_next()
    assert dispatch is not None
    requirements = Requirements()
    registry = PluginRegistryAuthority()
    reader = CoreExecutiveInputEvidenceReader(inputs, core.connection, registry, requirements)
    return SimpleNamespace(
        core=core,
        inputs=inputs,
        bridge=bridge,
        work=submitted,
        result=result,
        attention=attention,
        dispatch=dispatch,
        requirements=requirements,
        registry=registry,
        reader=reader,
        observed=observed,
    )


@pytest.mark.asyncio
async def test_actual_adopted_meaning_and_goals_reach_evidence_without_reinterpretation() -> None:
    value = await wired(with_goal=True)
    data = await value.reader.read(value.dispatch.selected_source)
    assert data.meaning is value.result.meaning
    assert tuple(item.event_id for item in data.source_events) == ("event:1",)
    goal = value.core.connection.current_reference().goals.recently_changed_goals[0]
    assert len(data.facts) == 1
    assert data.facts[0].fact_id == goal.goal_id
    assert data.facts[0].revision == goal.revision
    assert data.facts[0].payload == freeze_json(goal.to_dict())
    assert data.capabilities == ()


@pytest.mark.asyncio
async def test_live_registry_is_reread_with_original_permission_state() -> None:
    value = await wired()
    value.registry.register_manifest(manifest(), value.core.clock.now())
    first = await value.reader.read(value.dispatch.selected_source)
    assert first.capabilities == value.registry.capability_descriptors()
    value.registry.adopt_permission_grants(grants(0))
    second = await value.reader.read(value.dispatch.selected_source)
    assert second.capabilities == value.registry.capability_descriptors()
    assert first.capabilities != second.capabilities


@pytest.mark.parametrize("change", ["missing", "context", "candidate", "revision", "unsupported"])
@pytest.mark.asyncio
async def test_wrong_source_is_rejected(change: str) -> None:
    value = await wired()
    source = value.dispatch.selected_source
    if change == "missing":
        source = replace(source, kind=AttentionSourceKind.USER_INTERACTION, source_ref="absent")
    elif change == "context":
        source = replace(source, source_context_revision=99)
    elif change == "candidate":
        source = replace(source, source_ref="another-candidate")
    elif change == "revision":
        source = replace(source, source_revision=source.source_revision + 1)
    else:
        source = replace(source, kind=AttentionSourceKind.ACTIVITY)
    with pytest.raises(ValueError):
        await value.reader.read(source)


@pytest.mark.asyncio
async def test_user_source_reads_exact_event_and_old_context_is_not_relabelled() -> None:
    value = await wired()
    source = replace(
        value.dispatch.selected_source,
        kind=AttentionSourceKind.USER_INTERACTION,
        source_ref="event:1",
    )
    assert (await value.reader.read(source)).meaning is value.result.meaning
    apply_goal(value.core.goals, GoalTransitionOperation.CREATE, 0)
    source = replace(
        source,
        source_context_revision=value.core.connection.current_reference().context.source_context_revision,
    )
    with pytest.raises(ValueError, match="入力根拠の文脈"):
        await value.reader.read(source)


@pytest.mark.asyncio
async def test_bounded_retention_preserves_order_and_rejects_replacement() -> None:
    value = await wired()
    store = CoreAcceptedInputStore(1)
    store.retain(value.observed, value.result)
    with pytest.raises(ValueError, match="変更できません"):
        store.retain(value.observed, replace(value.result, request_id="different"))
    retained = store.read("event:1", value.result.source_context_revision)
    assert isinstance(retained, CoreAcceptedInput)
    assert retained.result is value.result
    other = replace(value.observed, envelope=replace(value.observed.envelope, event_id="other"))
    assert value.result.meaning is not None
    result = replace(
        value.result,
        source_event_id="other",
        meaning=replace(value.result.meaning, source_event_id="other"),
    )
    store.retain(other, result)
    with pytest.raises(ValueError, match="保持されていません"):
        store.read("event:1", value.result.source_context_revision)
    retained = store.read("other", result.source_context_revision)
    assert isinstance(retained, CoreAcceptedInput)
    assert retained.result is result


class PassivePort(Port):
    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
        result = await super().invoke(request)
        assert result.output is not None
        from app.domain.llm import StructuredPayload

        assert isinstance(result.output.value, Mapping)
        payload = dict(result.output.value)
        payload.update(outcome="defer", intents=(), rationale_refs=("event:1",))
        return replace(
            result, output=StructuredPayload(result.output.schema_id, freeze_json(payload))
        )


@pytest.mark.asyncio
async def test_actual_input_to_attention_to_decision_with_no_capabilities() -> None:
    value = await wired()
    authority = make_authority()
    binding = CoreExecutiveBinding(
        value.attention,
        value.reader,
        PassivePort(),
        executive_policy(),
        authority,
        value.core.clock,
    )
    result = await binding.deliberate(
        value.dispatch,
        request_id="decision",
        trace_id="trace",
        decision_id="decision",
        cancellation=CancellationToken(),
    )
    assert binding.latest_decision() is result
    assert value.requirements.calls == 1
    assert authority.has_committed(value.dispatch.trigger.trigger_id)


@pytest.mark.asyncio
async def test_precondition_failure_is_not_replaced_by_empty_facts() -> None:
    value = await wired()
    value.requirements.fail = True
    with pytest.raises(ValueError, match="前提条件"):
        await value.reader.read(value.dispatch.selected_source)


@pytest.mark.asyncio
async def test_minimum_boot_retains_real_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        bootstrap, "create_openai_port_from_environment", lambda *_a, **_k: SuccessfulPort()
    )
    app = bootstrap.build_minimum_core()
    source = work()
    context = app.input_context.snapshot().context
    payload = cast(InputMeaningBrainWorkPayload, source.payload)
    observed = replace(
        payload.event,
        envelope=replace(
            payload.event.envelope, revisions=RevisionVector(context.source_context_revision)
        ),
    )
    source = replace(
        source,
        envelope=replace(source.envelope, source_context_revision=context.source_context_revision),
        payload=replace(payload, event=observed, reference_context=context),
    )
    try:
        result = await app.bridge.execute(source, CancellationToken())
        assert result.meaning is not None
        assert app.bridge.inputs is not None
        retained = app.bridge.inputs.read("event-1", context.source_context_revision)
        assert isinstance(retained, CoreAcceptedInput)
        assert retained.result is result
    finally:
        await app.stop()


@pytest.mark.asyncio
async def test_cancellation_and_recancellation_reap_interpreter_without_retaining() -> None:
    value = await wired()
    entered, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    baseline = asyncio.all_tasks()

    class SlowPort(SuccessfulPort):
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                await release.wait()
            return await super().invoke(request)

    class Live:
        async def current_freshness_stamp(self) -> InputMeaningFreshnessStamp:
            return cast(
                InputMeaningFreshnessStamp, value.core.connection.current_reference().freshness
            )

    inputs = CoreAcceptedInputStore(2)
    bridge = InputMeaningBrainModulePort(
        InputMeaningInterpreter(SlowPort(), Live(), policy()), inputs
    )
    task = asyncio.create_task(bridge.execute(value.work, CancellationToken()))
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    await asyncio.wait_for(cancelled.wait(), 1)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(ValueError, match="保持されていません"):
        inputs.read("event:1", value.result.source_context_revision)
    assert not (asyncio.all_tasks() - baseline)


@pytest.mark.asyncio
async def test_failed_meaning_is_returned_without_retention() -> None:
    from tests.system_integration.test_early_boot import CountingUnavailableContext

    value = await wired()
    inputs = CoreAcceptedInputStore(2)
    bridge = InputMeaningBrainModulePort(
        InputMeaningInterpreter(SuccessfulPort(), CountingUnavailableContext(), policy()), inputs
    )
    result = await bridge.execute(value.work, CancellationToken())
    assert result.boundary_failure is not None
    with pytest.raises(ValueError, match="保持されていません"):
        inputs.read("event:1", value.result.source_context_revision)


@pytest.mark.asyncio
async def test_missing_authoritative_requirements_after_response_prevents_commit() -> None:
    value = await wired()
    port = PassivePort()
    port.release.clear()
    authority = make_authority()
    binding = CoreExecutiveBinding(
        value.attention, value.reader, port, executive_policy(), authority, value.core.clock
    )
    task = asyncio.create_task(
        binding.deliberate(
            value.dispatch,
            request_id="decision",
            trace_id="trace",
            decision_id="decision",
            cancellation=CancellationToken(),
        )
    )
    await asyncio.wait_for(port.started.wait(), 1)
    value.requirements.fail = True
    port.release.set()
    with pytest.raises(ValueError, match="必須要件"):
        await task
    assert not authority.has_committed(value.dispatch.trigger.trigger_id)
    assert binding.latest_decision() is None


@pytest.mark.parametrize("change", ["trace", "context", "event"])
@pytest.mark.asyncio
async def test_wrong_input_provenance_never_replaces_original(change: str) -> None:
    value = await wired()
    envelope = value.observed.envelope
    if change == "trace":
        envelope = replace(envelope, trace_id="other")
    elif change == "context":
        envelope = replace(envelope, revisions=RevisionVector(99))
    else:
        envelope = replace(envelope, event_id="other")
    with pytest.raises(ValueError, match="一致しません"):
        value.inputs.retain(replace(value.observed, envelope=envelope), value.result)
    assert value.inputs.read("event:1", value.result.source_context_revision).result is value.result


@pytest.mark.asyncio
async def test_activity_facts_come_from_the_actual_execution_owner() -> None:
    from app.composition.appraisal import CoreAppraisalBinding
    from app.composition.input_reference_context import CoreInputReferenceContextBinding
    from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
    from app.domain.executive import ExecutiveFactKind
    from tests.domain.appraisal.test_appraisal_paths import policy as appraisal_policy
    from tests.domain.plan_execution.test_progression import WaitingProvider, runner
    from tests.domain.plan_execution.test_progression import setup as plan_setup

    plan = plan_setup()
    provider = WaitingProvider(plan)
    task = asyncio.create_task(runner(plan, provider).advance(plan.scope_id))
    try:
        await asyncio.wait_for(provider.started.wait(), 1)
        command_id = provider.calls[0].command.command_id
        provider.release.set()
        await task
        context = CoreInputReferenceContextBinding(
            plan.goals, plan.activity, policy(), V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
        )
        context.set_activity_references((command_id,))
        core = setup()
        core.goals = plan.goals
        core.connection = CoreAppraisalBinding(
            context, core.owner, core.port, appraisal_policy(), core.clock
        )
        value = await wired(core=core)
        evidence = await value.reader.read(value.dispatch.selected_source)
        fact = next(item for item in evidence.facts if item.kind is ExecutiveFactKind.ACTIVITY)
        record = plan.activity.snapshot(command_id)
        assert record is not None
        assert fact.fact_id == command_id
        assert fact.revision == record.record_revision
        assert fact.payload == freeze_json(
            {
                "command_id": command_id,
                "status": record.result.status.value,
                "effect_uncertainty": record.effect_uncertainty.value,
            }
        )
    finally:
        provider.release.set()
        await asyncio.gather(task, return_exceptions=True)
