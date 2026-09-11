"""正規Registryと共通公開枠を使い、由来付き束縛の主要経路を確認する。"""

from collections.abc import Mapping
from dataclasses import replace
from threading import Event
from typing import cast

import pytest

from app.domain.activity_binding import (
    ActivityBindingAuthority,
    ActivityExecutionBindingPublication,
    ArgumentKind,
    ArgumentSourceFact,
    ArgumentSourceOwner,
    ArgumentSourceRelation,
    BindingInputPublicationOwner,
    OperationInputContract,
)
from app.domain.activity_binding.validation import selected_bindings
from app.domain.contracts import CapabilityRequirement
from app.domain.contracts.common import JsonValue
from app.domain.contracts.finalization import (
    AuthorityFinalizationFence,
    AuthorityFinalizationRequest,
    AuthorityFinalizationResult,
    FinalizationError,
)
from app.domain.executive import (
    CommittedExecutiveDecision,
    ExecutiveCommitState,
    ExecutiveContextSnapshot,
    ExecutiveDecisionCandidate,
)
from app.domain.executive.authority import ExecutiveFinalizationInput
from app.domain.plugin_registry.activity_binding import PluginActivityOperationAdapter
from tests.domain.plugin_registry.test_plugin_registry_adjacent import available_registry


def fixture() -> tuple[
    ActivityBindingAuthority,
    BindingInputPublicationOwner,
    ArgumentSourceOwner,
]:
    registry = available_registry()
    schema = BindingInputPublicationOwner(
        "schema-owner",
        OperationInputContract("plugin.run.input.v1", 1, (("query", ArgumentKind.STRING),)),
    )
    source = ArgumentSourceOwner(
        "source-owner",
        (ArgumentSourceFact("fact-1", "source-owner", 1, "plugin.run.input.v1", "typed-value"),),
    )
    owner = ActivityBindingAuthority(
        "binding-1", PluginActivityOperationAdapter(registry), schema, (source,)
    )
    return owner, schema, source


def publish(owner: ActivityBindingAuthority) -> ActivityExecutionBindingPublication:
    return owner.publish(
        revision=1,
        activity_type="activity",
        operation_ref="run",
        target_ref="target",
        capability_id="capability-a",
        relations=(ArgumentSourceRelation("query", "fact-1"),),
    )


def test_typed_binding_publication_and_exact_selection() -> None:
    owner, _, _ = fixture()
    pub = publish(owner)
    assert pub.value.arguments == {"query": "typed-value"}
    assert owner.capture() == pub
    requirements = (CapabilityRequirement("activity", "run"),)
    assert selected_bindings(
        (("binding-1", "activity", "target", None, requirements),),
        (pub,),
        (pub,),
        (pub.descriptor,),
    ) == (pub,)
    with pytest.raises(ValueError):
        replace(pub, value=replace(pub.value, operation_ref="other"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("ref", None),
        ("ref", "unknown"),
        ("operation", "other"),
        ("target", "other"),
        ("requirement", "other"),
    ],
)
def test_exact_identity_and_requirements_rejection(field: str, value: str | None) -> None:
    owner, _, _ = fixture()
    pub = publish(owner)
    request: dict[str, str | None] = {
        "ref": "binding-1",
        "operation": "run",
        "target": "target",
        "requirement": "run",
    }
    request[field] = value
    with pytest.raises(ValueError):
        selected_bindings(
            (
                (
                    request["ref"],
                    "activity",
                    request["target"],
                    request["operation"],
                    (CapabilityRequirement("activity", cast(str, request["requirement"])),),
                ),
            ),
            (pub,),
            (pub,),
            (pub.descriptor,),
        )


def test_source_change_and_schema_change_fail_closed() -> None:
    owner, schema, source = fixture()
    pub = publish(owner)
    source.publish((replace(source.capture().value[0], revision=2, value="changed"),))
    with pytest.raises(FinalizationError):
        pub.require_current()
    with pytest.raises(FinalizationError):
        owner.capture()
    owner2, schema2, _ = fixture()
    pub2 = publish(owner2)
    schema2.publish(replace(schema2.capture().value, revision=2))
    with pytest.raises(FinalizationError):
        pub2.require_current()


def test_empty_arguments_only_explicit_no_argument_contract() -> None:
    registry = available_registry()
    schema = BindingInputPublicationOwner(
        "schema", OperationInputContract("plugin.run.input.v1", 1, ())
    )
    owner = ActivityBindingAuthority("empty", PluginActivityOperationAdapter(registry), schema, ())
    pub = owner.publish(
        revision=1,
        activity_type="activity",
        operation_ref="run",
        target_ref=None,
        capability_id="capability-a",
        relations=(),
    )
    assert pub.value.arguments == {}
    schema.publish(
        OperationInputContract("plugin.run.input.v1", 2, (("query", ArgumentKind.STRING),))
    )
    with pytest.raises(ValueError):
        owner.publish(
            revision=2,
            activity_type="activity",
            operation_ref="run",
            target_ref=None,
            capability_id="capability-a",
            relations=(),
        )


def direct_fixture() -> tuple[
    ActivityBindingAuthority,
    BindingInputPublicationOwner,
    ArgumentSourceOwner,
    ExecutiveContextSnapshot,
    ExecutiveDecisionCandidate,
    ExecutiveCommitState,
]:
    from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
    from app.domain.executive import (
        ActivityIntentPayload,
        ExecutiveFactKind,
        ExecutiveFactRef,
        ExecutiveIntent,
        ExecutiveIntentKind,
        ExecutiveIntentRequirementRule,
        ExecutiveIntentRequirementsPolicy,
        ExecutiveOutcome,
        ExecutiveRequirementsOwner,
        RequirementMode,
        RequirementSelector,
    )
    from tests.domain.executive.test_executive import candidate, live_state, snapshot

    owner, schema, source = fixture()
    pub = publish(owner)
    requirement = CapabilityRequirement("activity", "run")
    rules = ExecutiveRequirementsOwner(V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)
    rules.publish(
        ExecutiveIntentRequirementsPolicy(
            "binding-policy",
            1,
            (
                ExecutiveIntentRequirementRule(
                    "activity",
                    1,
                    "binding-policy",
                    1,
                    ExecutiveIntentKind.ACTIVITY,
                    RequirementSelector(),
                    RequirementMode.CONSTANT,
                    (requirement,),
                    (),
                ),
            ),
        )
    )
    initial = snapshot()
    captured = rules.capture(
        replace(
            initial,
            requirements_generation=None,
            capabilities=(pub.descriptor,),
            activity_bindings=(pub,),
            facts=(
                *initial.facts,
                ExecutiveFactRef("target", ExecutiveFactKind.ENVIRONMENT, 1, {}),
            ),
        )
    )
    intent = ExecutiveIntent(
        "intent-activity",
        ExecutiveIntentKind.ACTIVITY,
        "引数へ変換しない自由文",
        ActivityIntentPayload("activity", "target", (), "binding-1"),
        required_capabilities=(requirement,),
    )
    proposed = replace(candidate(), outcome=ExecutiveOutcome.ACT, intents=(intent,))
    current = rules.prepare(
        captured,
        proposed,
        replace(live_state(), capabilities=(pub.descriptor,), activity_bindings=(pub,)),
    )
    return owner, schema, source, captured, proposed, current


def test_direct_committed_binding_and_projection() -> None:
    from app.domain.activity_binding.projector import direct_invocation
    from app.domain.executive import parse_candidate
    from tests.domain.executive.test_executive import NOW
    from tests.helpers.executive_requirements import fence_clock, make_authority

    _, _, _, captured, proposed, current = direct_fixture()
    wire = proposed.to_dict()
    wire.pop("created_at")
    assert parse_candidate(wire, captured, created_at=NOW) == proposed
    with fence_clock(lambda: NOW):
        committed = make_authority(captured).commit(
            proposed, captured, current=current, decision_id="decision-binding"
        )
    import json

    serialized = committed.to_dict()
    json.dumps(serialized, allow_nan=False)
    assert serialized["activity_bindings"] == [p.to_dict() for p in committed.activity_bindings]
    assert "_participant" not in json.dumps(serialized)
    invocation = direct_invocation(
        committed,
        proposed.intents[0],
        command_id="command",
        invocation_id="invocation",
        requested_at=NOW,
    )
    from app.domain.activity_execution import ActivityExecutionAuthority, ExecutionPreflightSnapshot
    from app.domain.contracts import ExecutionStatus

    assert invocation.primary_binding is not None
    assert invocation.primary_binding.capability_id == "capability-a"
    descriptor = committed.activity_bindings[0].descriptor
    admitted = ActivityExecutionAuthority().admit(
        invocation,
        ExecutionPreflightSnapshot(
            invocation.command.revisions,
            (replace(descriptor, capability_id="capability-0"), descriptor),
            (),
            NOW,
        ),
    )
    assert admitted.result.status is ExecutionStatus.ACCEPTED
    assert admitted.bindings == (invocation.primary_binding,)
    assert invocation.arguments == {"query": "typed-value"}
    assert invocation.operation_ref == "run"
    assert invocation.command.decision_id == committed.decision_id
    assert invocation.command.required_capabilities == proposed.intents[0].required_capabilities


def test_direct_source_update_blocks_commit() -> None:
    from tests.helpers.executive_requirements import make_authority

    _, _, source, captured, proposed, current = direct_fixture()
    source.publish((replace(source.capture().value[0], revision=2, value="changed"),))
    authority = make_authority(captured)
    with pytest.raises(FinalizationError):
        authority.commit(proposed, captured, current=current, decision_id="stale")
    assert not authority.has_committed(captured.trigger_id)


def test_plan_commit_and_mechanical_projection() -> None:
    from app.domain.activity_binding.projector import plan_execution_inputs
    from app.domain.contracts import PreconditionRef
    from app.domain.goal_planning import GoalPlanningAuthority
    from tests.domain.goal_planning.test_goal_planning import NOW, candidate, context, current

    owner = GoalPlanningAuthority()
    plan = owner.commit(candidate(), context(), current(), plan_id="plan-binding", committed_at=NOW)
    bindings, facts = plan_execution_inputs(
        plan, owner, (PreconditionRef("pre-ready", "equals", "target-1", True),)
    )
    assert bindings[0].primary_binding is not None
    assert (
        bindings[0].primary_binding.capability_id == plan.activity_bindings[0].value.capability_id
    )
    assert (
        bindings[0].primary_binding.descriptor_revision
        == plan.activity_bindings[0].value.capability_revision
    )
    assert bindings[0].to_dict()["primary_binding"] == bindings[0].primary_binding.to_dict()
    assert bindings[0].arguments == {"query": "資料"}
    assert facts[0].reference_id == "goal-1"
    assert facts[0].value == "資料"


def test_rejected_binding_publish_keeps_value_and_refreshes_own_token() -> None:
    owner, _, _ = fixture()
    old = publish(owner)
    with pytest.raises(ValueError):
        owner.publish(
            revision=1,
            activity_type="activity",
            operation_ref="inspect",
            target_ref="target",
            capability_id="capability-a",
            relations=(),
        )
    with pytest.raises(FinalizationError):
        old.require_current()
    fresh = owner.capture()
    assert fresh.value == old.value
    fresh.require_current()


@pytest.mark.parametrize("update", ["same_revision", "noop", "retire"])
def test_source_failed_noop_and_restart_tokens_fail_closed(update: str) -> None:
    owner, _, source = fixture()
    old = publish(owner)
    fact = source.capture().value[0]
    if update == "same_revision":
        with pytest.raises(ValueError):
            source.publish((replace(fact, value="different"),))
    elif update == "noop":
        source.publish((fact,))
    else:
        source.close()
    with pytest.raises(FinalizationError):
        old.require_current()


def test_unrelated_binding_update_does_not_invalidate_selected_publication() -> None:
    owner, _, _ = fixture()
    old = publish(owner)
    other = ActivityBindingAuthority("other", owner.operation_owner, owner.schema, owner.sources)
    publish(other)
    publish(other)
    old.require_current()


def test_strict_json_types_and_mutable_alias() -> None:
    owner, _, source = fixture()
    pub = publish(owner)
    raw = {"values": [1, True]}
    fact = ArgumentSourceFact(
        "mutable", "source-owner", 1, "plugin.run.input.v1", cast(JsonValue, raw)
    )
    raw["values"].append(2)
    assert isinstance(fact.value, Mapping)
    assert fact.value["values"] == (1, True)
    assert not ArgumentKind.INTEGER.accepts(True)
    with pytest.raises(ValueError):
        replace(source.capture().value[0], revision=True)
    with pytest.raises(ValueError):
        replace(pub.value, arguments={"query": "self-reported"})
    with pytest.raises(ValueError):
        replace(pub.value, relations=())
    with pytest.raises(ValueError):
        replace(pub.value, sources=(*pub.value.sources, *pub.value.sources))


def test_final_fence_rejects_source_change_after_initial_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.helpers.executive_requirements import make_authority

    _, _, source, captured, proposed, current = direct_fixture()
    original = AuthorityFinalizationFence.finalize

    def change_then_finalize(
        self: AuthorityFinalizationFence,
        request: AuthorityFinalizationRequest[
            ExecutiveFinalizationInput, CommittedExecutiveDecision
        ],
        *,
        cancellation: Event | None = None,
    ) -> AuthorityFinalizationResult[CommittedExecutiveDecision]:
        source.publish((replace(source.capture().value[0], revision=2, value="changed"),))
        return original(self, request, cancellation=cancellation)

    monkeypatch.setattr(AuthorityFinalizationFence, "finalize", change_then_finalize)
    authority = make_authority(captured)
    with pytest.raises(FinalizationError):
        authority.commit(proposed, captured, current=current, decision_id="race")
    assert not authority.has_committed(captured.trigger_id)


def test_plan_stale_binding_rejects_before_publication() -> None:
    from app.domain.goal_planning import GoalPlanningAuthority
    from tests.domain.goal_planning.test_goal_planning import NOW, candidate, context, current

    owner, _, source = fixture()
    pub = owner.publish(
        revision=1,
        activity_type="activity",
        operation_ref="run",
        target_ref="target-1",
        capability_id="capability-a",
        relations=(ArgumentSourceRelation("query", "fact-1"),),
    )
    snap = replace(
        context(deterministic=False),
        capabilities=(pub.descriptor,),
        planning_requirements=(CapabilityRequirement("activity", "run"),),
        activity_bindings=(pub,),
    )
    value = candidate()
    value = replace(
        value,
        steps=(
            replace(
                value.steps[0],
                binding_ref="binding-1",
                activity_type="activity",
                operation_ref="run",
                required_capabilities=(CapabilityRequirement("activity", "run"),),
            ),
        ),
    )
    live = replace(current(), capabilities=(pub.descriptor,), activity_bindings=(pub,))
    source.publish((replace(source.capture().value[0], revision=2, value="changed"),))
    planning = GoalPlanningAuthority()
    with pytest.raises(FinalizationError):
        planning.commit(value, snap, live, plan_id="stale", committed_at=NOW)
    assert planning.current_plan(value.goal_id) is None


def test_concurrent_publication_and_independent_read() -> None:
    from concurrent.futures import ThreadPoolExecutor

    owner, _, _ = fixture()
    initial = publish(owner)

    def republish(_: int) -> ActivityExecutionBindingPublication:
        return publish(owner)

    with ThreadPoolExecutor(max_workers=4) as pool:
        publications = list(pool.map(republish, range(8)))
    assert len({p.tokens[0].generation for p in publications}) == 8
    assert owner.capture().value == initial.value


def test_schema_mismatch_and_unknown_binding_fail_closed() -> None:
    owner, schema, _ = fixture()
    schema.publish(
        OperationInputContract("plugin.run.input.v1", 2, (("query", ArgumentKind.INTEGER),))
    )
    with pytest.raises(ValueError, match="型"):
        publish(owner)
    unknown = BindingInputPublicationOwner(
        "schema", OperationInputContract("unknown-schema", 1, ())
    )
    empty = ActivityBindingAuthority("unknown", owner.operation_owner, unknown, ())
    with pytest.raises(ValueError, match="入力契約"):
        empty.publish(
            revision=1,
            activity_type="activity",
            operation_ref="run",
            target_ref=None,
            capability_id="capability-a",
            relations=(),
        )


def test_bounds_and_duplicate_publication_rejection() -> None:
    from app.domain.activity_binding.validation import validate_publications
    from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY as policy

    owner, _, _ = fixture()
    pub = publish(owner)
    with pytest.raises(ValueError, match="容量"):
        ArgumentSourceFact(
            "large", "source", 1, "schema", "x" * policy.executive.max_fact_payload_json_bytes
        )
    with pytest.raises(ValueError, match="重複"):
        validate_publications(
            (pub, pub), max_count=2, max_bytes=policy.executive.max_fact_payload_json_bytes
        )
    with pytest.raises(ValueError, match="容量"):
        validate_publications((pub,), max_count=1, max_bytes=1)
    with pytest.raises(ValueError, match="上限"):
        OperationInputContract(
            "schema",
            1,
            tuple(
                (f"arg-{i}", ArgumentKind.STRING)
                for i in range(policy.executive.max_refs_per_intent + 1)
            ),
        )


def test_direct_uses_explicit_binding_without_selecting_sibling() -> None:
    from tests.domain.executive.test_executive import NOW
    from tests.helpers.executive_requirements import fence_clock, make_authority

    owner, _, _, captured, proposed, current = direct_fixture()
    other = ActivityBindingAuthority("other", owner.operation_owner, owner.schema, owner.sources)
    sibling = publish(other)
    captured = replace(captured, activity_bindings=(*captured.activity_bindings, sibling))
    current = replace(current, activity_bindings=(*current.activity_bindings, sibling))
    publish(other)
    with fence_clock(lambda: NOW):
        decision = make_authority(captured).commit(
            proposed, captured, current=current, decision_id="exact"
        )
    assert [p.value.binding_id for p in decision.activity_bindings] == ["binding-1"]


def test_plan_requires_all_step_bindings() -> None:
    from app.domain.goal_planning import GoalPlanningAuthority
    from tests.domain.goal_planning.test_goal_planning import NOW, candidate, context, current

    value = candidate()
    for ref in (None, "unknown"):
        proposed = replace(value, steps=(replace(value.steps[0], binding_ref=ref),))
        with pytest.raises(ValueError, match="binding"):
            GoalPlanningAuthority().commit(
                proposed,
                context(deterministic=False),
                current(),
                plan_id="unknown",
                committed_at=NOW,
            )


def test_retired_binding_cannot_be_used_after_owner_restart() -> None:
    owner, schema, source = fixture()
    old = publish(owner)
    owner.close()
    replacement = ActivityBindingAuthority("binding-1", owner.operation_owner, schema, (source,))
    new = publish(replacement)
    new.require_current()
    with pytest.raises(FinalizationError):
        old.require_current()


def test_plan_authorization_fences_argument_source(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.domain.executive import PlanExecutionIntentPayload
    from app.domain.goal_planning import GoalPlanningAuthority
    from tests.domain.executive.test_executive import REVISIONS
    from tests.domain.executive.test_plan_authorization import inputs
    from tests.domain.goal_planning.test_goal_planning import NOW, candidate, context, current
    from tests.helpers.activity_binding import planning_binding
    from tests.helpers.executive_requirements import capture_plans, fence_clock, make_authority

    pub = planning_binding.__wrapped__()
    snap = context()
    assert REVISIONS.goal_revision is not None
    snap = replace(
        snap,
        revisions=REVISIONS,
        goal_context=replace(snap.goal_context, goal_revision=REVISIONS.goal_revision),
        activity_bindings=(pub,),
    )
    plan = GoalPlanningAuthority().commit(
        replace(candidate(), revisions=REVISIONS),
        snap,
        replace(current(), revisions=REVISIONS, activity_bindings=(pub,)),
        plan_id="fresh-plan",
        committed_at=NOW,
    )
    proposed, captured, live = inputs()
    scope = replace(captured.plan_scopes[0], plan=plan)
    captured = capture_plans(replace(captured, plan_scopes=(scope,)))
    proposed = replace(
        proposed,
        intents=(replace(proposed.intents[0], payload=PlanExecutionIntentPayload(scope.scope_id)),),
    )
    assert captured.requirements_generation is not None
    live = captured.requirements_generation.owner.prepare(
        captured, proposed, replace(live, plan_scopes=(scope,))
    )
    original = AuthorityFinalizationFence.finalize

    def mutate_then_finalize(
        self: AuthorityFinalizationFence,
        request: AuthorityFinalizationRequest[
            ExecutiveFinalizationInput, CommittedExecutiveDecision
        ],
        *,
        cancellation: Event | None = None,
    ) -> AuthorityFinalizationResult[CommittedExecutiveDecision]:
        with pub.tokens[-1]._participant.mutation():
            pass
        return original(self, request, cancellation=cancellation)

    monkeypatch.setattr(AuthorityFinalizationFence, "finalize", mutate_then_finalize)
    authority = make_authority(captured)
    with fence_clock(lambda: NOW), pytest.raises(FinalizationError):
        authority.commit(proposed, captured, current=live, decision_id="stale-plan")
    assert not authority.has_committed(captured.trigger_id)


@pytest.mark.parametrize("ambiguous", [False, True])
def test_direct_projection_rejects_missing_or_ambiguous_primary(
    monkeypatch: pytest.MonkeyPatch, ambiguous: bool
) -> None:
    from app.domain.activity_binding import projector
    from tests.domain.executive.test_executive import NOW
    from tests.helpers.executive_requirements import fence_clock, make_authority

    _, _, _, captured, proposed, current = direct_fixture()
    with fence_clock(lambda: NOW):
        decision = make_authority(captured).commit(
            proposed, captured, current=current, decision_id="primary-gate"
        )
    from app.domain.executive.projector import to_system_command

    command = to_system_command(decision, proposed.intents[0], command_id="cmd")
    requirement = command.required_capabilities[0]
    invalid = replace(
        command,
        required_capabilities=(
            (requirement, replace(requirement, allow_degraded=True)) if ambiguous else ()
        ),
    )
    monkeypatch.setattr(projector, "to_system_command", lambda *a, **k: invalid)
    with pytest.raises(ValueError, match="primary"):
        projector.direct_invocation(
            decision, proposed.intents[0], command_id="cmd", invocation_id="inv", requested_at=NOW
        )
