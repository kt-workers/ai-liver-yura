"""登録済みOwnerから要件・実測事実・計画根拠を本番入口へ供給する。"""

import asyncio
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

import pytest

from app.composition.executive import CoreExecutiveBinding
from app.composition.executive_requirements import (
    CoreExecutivePlanReferences,
    CoreExecutiveRequirementsReader,
    build_core_executive_input_evidence,
)
from app.domain.attention import AttentionSource
from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY as BOUNDS
from app.domain.contracts import CapabilityRequirement
from app.domain.contracts.common import freeze_json
from app.domain.contracts.finalization import AuthorityReadPublication, FinalizationError
from app.domain.executive import (
    ExecutiveDecisionAuthority,
    ExecutiveIntent,
    ExecutiveIntentKind,
    ExecutiveIntentRequirementRule,
    ExecutiveIntentRequirementsPolicy,
    ExecutivePreconditionRequirement,
    ExecutiveRequirementsOwner,
    PreconditionFact,
    RequirementMode,
    RequirementSelector,
    RequirementsFailureCode,
    RequirementSourcePublication,
    RequirementsRejected,
    SpeechIntentPayload,
)
from app.domain.llm import LLMRoleRequest, LLMRoleResult, StructuredPayload
from app.runtime.kernel import CancellationToken
from tests.domain.executive.test_executive import candidate, policy, snapshot
from tests.domain.plan_execution.test_progression import setup as plan_setup
from tests.domain.plugin_registry.test_plugin_registry import available_registry, grants
from tests.system_integration.test_core_executive import Port
from tests.system_integration.test_core_input_evidence import wired


class GoalFacts:
    """試験で構成した目標所有者から現在の存在事実を読み取る。"""

    def __init__(self, goals: Any) -> None:
        self.goals = goals
        self.fail = False
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()

    async def preconditions_for(
        self, source: AttentionSource
    ) -> tuple[AuthorityReadPublication[PreconditionFact], ...]:
        self.started.set()
        await self.release.wait()
        if self.fail:
            raise RuntimeError("実測事実を取得できません")
        current = self.goals.snapshot_publication()
        return (
            AuthorityReadPublication(
                PreconditionFact("goal-present", "goal-1", "exists", bool(current.value.goals)),
                current.tokens,
            ),
        )


def registered_owner() -> ExecutiveRequirementsOwner:
    owner = ExecutiveRequirementsOwner(BOUNDS)
    owner.publish(
        ExecutiveIntentRequirementsPolicy(
            "production-test",
            1,
            (
                ExecutiveIntentRequirementRule(
                    "speech-goal",
                    1,
                    "production-test",
                    1,
                    ExecutiveIntentKind.SPEECH,
                    RequirementSelector(),
                    RequirementMode.CONSTANT,
                    (CapabilityRequirement("plugin", "execute"),),
                    (ExecutivePreconditionRequirement("goal-present", True),),
                ),
            ),
        )
    )
    return owner


class GoalPort(Port):
    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
        result = await super().invoke(request)
        assert result.output is not None and isinstance(result.output.value, Mapping)
        intent = ExecutiveIntent(
            "speak",
            ExecutiveIntentKind.SPEECH,
            "現在の目標に対応する",
            SpeechIntentPayload("goal-1"),
            ("goal-1",),
            (CapabilityRequirement("plugin", "execute"),),
            (ExecutivePreconditionRequirement("goal-present", True),),
        )
        payload: dict[str, object] = dict(result.output.value)
        payload.update(
            intents=(intent.to_dict(),),
            goal_transition_intents=(),
            commitment_transition_intents=(),
            rationale_refs=("event:1",),
        )
        return replace(
            result, output=StructuredPayload(result.output.schema_id, freeze_json(payload))
        )


async def production() -> Any:
    value = await wired(with_goal=True)
    value.owner = registered_owner()
    value.facts = GoalFacts(value.core.goals)
    value.requirements = CoreExecutiveRequirementsReader(value.owner, value.facts, BOUNDS)
    value.registry = available_registry()
    value.reader = build_core_executive_input_evidence(
        value.inputs,
        value.core.connection,
        value.registry,
        value.requirements,
    )
    value.authority = ExecutiveDecisionAuthority(value.owner)
    value.port = GoalPort()
    value.binding = CoreExecutiveBinding(
        value.attention, value.reader, value.port, policy(), value.authority, value.core.clock
    )
    return value


async def deliberate(value: Any) -> Any:
    return await value.binding.deliberate(
        value.dispatch,
        request_id="requirements",
        trace_id="trace",
        decision_id="requirements",
        cancellation=CancellationToken(),
    )


@pytest.mark.asyncio
async def test_production_factory_supplies_real_goal_facts_and_registry_requirements() -> None:
    value = await production()
    decision = await deliberate(value)
    assert decision.requirement_derivations[0].provenance.rule_id == "speech-goal"
    assert decision.validated_preconditions == (
        PreconditionFact("goal-present", "goal-1", "exists", True),
    )
    assert {token.owner_identity for token in decision.evidence_tokens} == {
        "PluginRegistryAuthority",
        "GoalCommitmentStore",
    }
    assert decision.to_dict()["evidence_tokens"]
    assert value.binding.latest_decision() is decision
    assert value.registry.capability_descriptors()[0].capability_type == "plugin"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["unregistered", "facts", "policy", "capability"])
async def test_failed_or_changed_registered_source_never_commits(failure: str) -> None:
    value = await production()
    if failure == "unregistered":
        value.owner = ExecutiveRequirementsOwner(BOUNDS)
        value.requirements.owner = value.owner
    if failure == "facts":
        value.facts.fail = True
    value.port.release.clear()
    pending = asyncio.create_task(deliberate(value))
    if failure in ("policy", "capability"):
        await asyncio.wait_for(value.port.started.wait(), 1)
        if failure == "policy":
            current = value.owner.current_generation()
            value.owner.publish(
                replace(
                    current.policy,
                    revision=2,
                    rules=tuple(replace(r, policy_revision=2) for r in current.policy.rules),
                )
            )
        else:
            value.registry.adopt_permission_grants(grants(1, permissions=()))
    value.port.release.set()
    with pytest.raises(ValueError):
        await pending
    assert not value.authority.has_committed(value.dispatch.trigger.trigger_id)
    assert value.binding.latest_decision() is None


@pytest.mark.asyncio
async def test_cancellation_during_real_precondition_read_reaps_operation() -> None:
    value = await production()
    value.facts.release.clear()
    before = asyncio.all_tasks()
    pending = asyncio.create_task(deliberate(value))
    await asyncio.wait_for(value.facts.started.wait(), 1)
    pending.cancel()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert not value.port.requests
    assert not value.authority.has_committed(value.dispatch.trigger.trigger_id)
    assert not (asyncio.all_tasks() - before)


@pytest.mark.asyncio
async def test_concurrent_requirement_reads_keep_each_snapshot_and_intent_identity() -> None:
    value = await production()
    first = value.owner.capture(snapshot("first"))
    second = value.owner.capture(snapshot("second"))
    original = candidate()
    a = replace(
        original, trigger_id="first", intents=(replace(original.intents[0], intent_id="a"),)
    )
    b = replace(
        original, trigger_id="second", intents=(replace(original.intents[0], intent_id="b"),)
    )
    x, y = await asyncio.gather(
        value.requirements.requirements_for(first, a),
        value.requirements.requirements_for(second, b),
    )
    assert x[0].intent_id == "a" and y[0].intent_id == "b"
    assert x[0].capabilities == (CapabilityRequirement("plugin", "execute"),)
    assert value.owner.current_generation() is first.requirements_generation


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["scope", "context"])
@pytest.mark.parametrize("changed", ["none", "update", "restart"])
async def test_actual_plan_owner_publication_matches_registered_requirement_source(
    kind: str,
    changed: str,
) -> None:
    value = await production()
    plan = plan_setup()
    publication = (
        plan.owner.scope_publication(plan.scope_id)
        if kind == "scope"
        else plan.owner.observation_publication(plan.scope_id)
    )
    generation = value.owner.current_generation()
    value.owner.publish(
        generation.policy,
        (RequirementSourcePublication("plan", 1, publication.value, publication.tokens),),
    )
    source = value.dispatch.selected_source
    refs = CoreExecutivePlanReferences(
        (plan.scope_id,) if kind == "scope" else (),
        (plan.scope_id,) if kind == "context" else (),
    )
    if changed == "restart":
        plan = plan_setup()
    reader = CoreExecutiveRequirementsReader(
        value.owner,
        value.facts,
        BOUNDS,
        plans=plan.owner,
        references={(source.kind, source.source_ref): refs},
    )
    if changed != "none":
        if changed == "update":
            with plan.owner.finalization_participant.mutation():
                pass
        with pytest.raises(RequirementsRejected) as failure:
            reader.plans_for(source)
        assert failure.value.failure.code is (
            RequirementsFailureCode.SOURCE_UNAVAILABLE
            if changed == "restart"
            else RequirementsFailureCode.STALE_SOURCE
        )
    else:
        scopes, contexts = reader.plans_for(source)
        assert (
            scopes[0] if kind == "scope" else contexts[0]
        ).to_dict() == publication.value.to_dict()
        evidence = build_core_executive_input_evidence(
            value.inputs, value.core.connection, value.registry, reader
        )
        projected = await evidence.read(source)
        assert projected.plan_scopes == scopes and projected.plan_progress_contexts == contexts


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["duplicate", "count", "payload"])
async def test_precondition_reader_rejects_unbounded_or_ambiguous_facts(fault: str) -> None:
    value = await production()
    fact = PreconditionFact("test", "subject", "equals", "x")
    values: tuple[PreconditionFact, ...]
    if fault == "duplicate":
        values = (fact, fact)
    elif fault == "count":
        values = tuple(
            replace(fact, precondition_id=f"p-{i}")
            for i in range(BOUNDS.executive.max_precondition_facts + 1)
        )
    else:
        values = (replace(fact, actual="x" * BOUNDS.executive.max_fact_payload_json_bytes),)

    class Facts:
        async def preconditions_for(
            self, source: AttentionSource
        ) -> tuple[AuthorityReadPublication[PreconditionFact], ...]:
            return tuple(
                AuthorityReadPublication(item, value.core.goals.snapshot_publication().tokens)
                for item in values
            )

    reader = CoreExecutiveRequirementsReader(value.owner, Facts(), BOUNDS)
    with pytest.raises(RequirementsRejected) as failure:
        await reader.preconditions_for(value.dispatch.selected_source)
    assert failure.value.failure.code is RequirementsFailureCode.INVALID_PROJECTION


@pytest.mark.asyncio
async def test_registry_update_after_current_read_cannot_commit_old_capability() -> None:
    value = await production()

    class UpdatingAuthority(ExecutiveDecisionAuthority):
        def commit(self, *args: Any, **kwargs: Any) -> Any:
            value.registry.adopt_permission_grants(grants(1, permissions=()))
            return super().commit(*args, **kwargs)

    value.authority = UpdatingAuthority(value.owner)
    value.binding = CoreExecutiveBinding(
        value.attention, value.reader, value.port, policy(), value.authority, value.core.clock
    )
    with pytest.raises(FinalizationError, match="GENERATION_MISMATCH"):
        await deliberate(value)
    assert not value.authority.has_committed(value.dispatch.trigger.trigger_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("used", [True, False])
async def test_only_used_fact_owner_is_fenced_after_current_read(used: bool) -> None:
    from app.domain.goals import GoalCommitmentStore

    value = await production()
    unused = GoalCommitmentStore()
    original = value.facts

    class Facts:
        async def preconditions_for(
            self,
            source: AttentionSource,
        ) -> tuple[AuthorityReadPublication[PreconditionFact], ...]:
            actual = await original.preconditions_for(source)
            extra = AuthorityReadPublication(
                PreconditionFact("unused", "another-goal", "exists", False),
                unused.snapshot_publication().tokens,
            )
            return (*actual, extra)

    value.requirements = CoreExecutiveRequirementsReader(value.owner, Facts(), BOUNDS)
    value.reader = build_core_executive_input_evidence(
        value.inputs,
        value.core.connection,
        value.registry,
        value.requirements,
    )

    class UpdatingAuthority(ExecutiveDecisionAuthority):
        def commit(self, *args: Any, **kwargs: Any) -> Any:
            owner = value.core.goals if used else unused
            with owner.finalization_participant.mutation():
                pass
            return super().commit(*args, **kwargs)

    value.authority = UpdatingAuthority(value.owner)
    value.binding = CoreExecutiveBinding(
        value.attention, value.reader, value.port, policy(), value.authority, value.core.clock
    )
    if used:
        with pytest.raises(FinalizationError, match="GENERATION_MISMATCH"):
            await deliberate(value)
        assert not value.authority.has_committed(value.dispatch.trigger.trigger_id)
    else:
        decision = await deliberate(value)
        assert unused.finalization_participant.token() not in decision.evidence_tokens


def test_registry_publication_invalidates_even_failed_and_noop_updates() -> None:
    registry = available_registry()
    before = registry.capability_publication()
    registry.adopt_permission_grants(grants(0))
    noop = registry.capability_publication()
    assert noop.value == before.value and noop.tokens != before.tokens
    with pytest.raises(ValueError):
        registry.adopt_permission_grants(grants(0, permissions=()))
    rejected = registry.capability_publication()
    assert rejected.value == noop.value and rejected.tokens != noop.tokens
