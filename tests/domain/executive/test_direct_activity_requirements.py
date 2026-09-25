"""Direct要件の正規source・意味参照・世代の独立性を検証する。"""

from copy import copy
from dataclasses import replace

import pytest

from app.domain.activity_binding import ActivityBindingAuthority, ArgumentSourceRelation
from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY as BOUNDS
from app.domain.contracts import CapabilityRequirement
from app.domain.contracts.finalization import FinalizationError
from app.domain.executive import (
    ActivityIntentPayload,
    DirectActivityRequirementSource,
    DirectActivityRequirementSourceSpec,
    DirectActivityRequirementsOwner,
    ExecutiveDecisionAuthority,
    ExecutiveFactKind,
    ExecutiveFactRef,
    ExecutivePreconditionRequirement,
    ExecutiveRequirementsOwner,
    RequirementsRejected,
)
from tests.domain.activity_binding.test_binding import direct_fixture, fixture, publish
from tests.domain.executive.test_executive import NOW
from tests.helpers.direct_activity_requirements import requirements_owner, source_owner
from tests.helpers.executive_requirements import fence_clock


def test_publication_proof_auxiliary_and_explicit_conditions() -> None:
    binding, _, _ = fixture()
    publish(binding)
    caps = (CapabilityRequirement("activity", "run"), CapabilityRequirement("network", "access"))
    conditions = (ExecutivePreconditionRequirement("network-ready", True),)
    owner = source_owner(binding, caps, conditions)
    pub = owner.capture()
    assert isinstance(pub.value, DirectActivityRequirementSource)
    assert pub.value.record.capabilities == caps
    assert pub.value.record.preconditions == conditions
    assert pub.value.binding_publication == binding.capture()
    with pytest.raises(ValueError):
        replace(pub.value)
    with pytest.raises(ValueError):
        replace(pub, tokens=pub.tokens[1:])
    owner.close()
    with pytest.raises((ValueError, FinalizationError)):
        owner.capture()


@pytest.mark.parametrize(
    "change",
    ["binding", "revision", "type", "target", "primary", "duplicate", "conditions", "contract"],
)
def test_invalid_record_or_binding_is_rejected(change: str) -> None:
    binding, _, _ = fixture()
    publish(binding)
    owner = source_owner(binding, (CapabilityRequirement("activity", "run"),))
    pub = owner.capture()
    assert isinstance(pub.value, DirectActivityRequirementSource)
    old = pub.value.record
    with pytest.raises((ValueError, FinalizationError)):
        if change == "binding":
            record = replace(old, revision=2, binding_ref="other")
        elif change == "revision":
            record = replace(old, revision=2, binding_revision=2)
        elif change == "type":
            record = replace(old, revision=2, activity_type="other")
        elif change == "target":
            record = replace(old, revision=2, target_ref="other")
        elif change == "primary":
            record = replace(old, revision=2, capabilities=())
        elif change == "duplicate":
            record = replace(old, revision=2, capabilities=(*old.capabilities, *old.capabilities))
        elif change == "conditions":
            condition = ExecutivePreconditionRequirement("ready", True)
            record = replace(old, revision=2, preconditions=(condition, condition))
        else:
            record = replace(old, contract_id="other")
        owner.publish(record)


def test_revision_history_and_binding_target_update() -> None:
    binding, _, _ = fixture()
    publish(binding)
    owner = source_owner(binding, (CapabilityRequirement("activity", "run"),))
    pub = owner.capture()
    assert isinstance(pub.value, DirectActivityRequirementSource)
    old = pub.value.record
    with pytest.raises(FinalizationError):
        owner.publish(replace(old, capabilities=(CapabilityRequirement("activity", "run", True),)))
    owner.publish(replace(old, revision=2))
    with pytest.raises(FinalizationError):
        owner.publish(old)
    binding.publish(
        revision=2,
        activity_type="activity",
        operation_ref="run",
        target_ref="other",
        capability_id="capability-a",
        relations=(ArgumentSourceRelation("query", "fact-1"),),
    )
    with pytest.raises(FinalizationError):
        owner.capture()
    fresh = owner.publish(replace(old, revision=3, binding_revision=2, target_ref="other"))
    assert isinstance(fresh.value, DirectActivityRequirementSource)
    assert fresh.value.record.binding_ref == old.binding_ref


@pytest.mark.parametrize("ref", [None, "unknown"])
def test_unknown_candidate_reference(ref: str | None) -> None:
    _, _, _, snap, proposed, _ = direct_fixture()
    assert snap.requirements_generation is not None
    intent = proposed.intents[0]
    assert isinstance(intent.payload, ActivityIntentPayload)
    proposed = replace(
        proposed, intents=(replace(intent, payload=replace(intent.payload, binding_ref=ref)),)
    )
    result = snap.requirements_generation.owner.derive(snap, proposed)
    assert result.failure is not None
    assert not result.values


def test_capture_rejects_duplicate_missing_and_forged_request() -> None:
    _, _, _, snap, proposed, _ = direct_fixture()
    generation = snap.requirements_generation
    assert generation is not None
    with pytest.raises(RequirementsRejected):
        generation.owner.capture(
            replace(snap, activity_bindings=(*snap.activity_bindings, *snap.activity_bindings))
        )
    missing = ExecutiveRequirementsOwner(BOUNDS)
    with pytest.raises(RequirementsRejected):
        missing.publish(generation.policy)


def test_request_copy_is_not_an_issued_capture() -> None:
    _, _, _, snap, proposed, _ = direct_fixture()
    generation = snap.requirements_generation
    assert generation is not None
    with pytest.raises(RequirementsRejected):
        replace(generation)
    forged = copy(generation)
    assert (
        generation.owner.derive(replace(snap, requirements_generation=forged), proposed).failure
        is not None
    )
    assert generation.base_generation is generation.owner.current_generation()
    assert generation.serial == generation.base_generation.serial
    assert generation.to_dict()


@pytest.mark.parametrize("constraint", ["fact-a", "fact-b"])
def test_constraint_variant_uses_same_source_and_commits(constraint: str) -> None:
    _, _, _, snap, proposed, live = direct_fixture()
    snap = replace(
        snap,
        facts=(
            *snap.facts,
            ExecutiveFactRef("fact-a", ExecutiveFactKind.ENVIRONMENT, 1, {}),
            ExecutiveFactRef("fact-b", ExecutiveFactKind.ENVIRONMENT, 1, {}),
        ),
    )
    intent = proposed.intents[0]
    assert isinstance(intent.payload, ActivityIntentPayload)
    proposed = replace(
        proposed,
        intents=(replace(intent, payload=replace(intent.payload, constraint_refs=(constraint,))),),
    )
    assert snap.requirements_generation is not None
    owner = snap.requirements_generation.owner
    live = owner.prepare(snap, proposed, live)
    with fence_clock(lambda: NOW):
        committed = ExecutiveDecisionAuthority(owner).commit(
            proposed, snap, current=live, decision_id="direct"
        )
    assert committed.candidate.intents[0].payload == proposed.intents[0].payload


@pytest.mark.parametrize("change", ["missing", "extra", "degraded", "precondition"])
def test_candidate_cannot_modify_requirements(change: str) -> None:
    _, _, _, snap, proposed, live = direct_fixture()
    intent = proposed.intents[0]
    if change == "missing":
        intent = replace(intent, required_capabilities=())
    elif change == "extra":
        intent = replace(
            intent,
            required_capabilities=(
                *intent.required_capabilities,
                CapabilityRequirement("network", "access"),
            ),
        )
    elif change == "degraded":
        intent = replace(
            intent, required_capabilities=(CapabilityRequirement("activity", "run", True),)
        )
    else:
        intent = replace(
            intent, preconditions=(ExecutivePreconditionRequirement("invented", True),)
        )
    proposed = replace(proposed, intents=(intent,))
    assert snap.requirements_generation is not None
    owner = snap.requirements_generation.owner
    live = owner.prepare(snap, proposed, live)
    with pytest.raises(RequirementsRejected):
        ExecutiveDecisionAuthority(owner).commit(proposed, snap, current=live, decision_id="direct")


def test_unselected_source_update_does_not_invalidate_selected_request() -> None:
    binding, _, _, snap, proposed, live = direct_fixture()
    other_base, schema, arguments = fixture()
    other = ActivityBindingAuthority("binding-2", other_base.operation_owner, schema, (arguments,))
    publish(other)
    first = source_owner(binding, (CapabilityRequirement("activity", "run"),))
    second = source_owner(other, (CapabilityRequirement("activity", "run"),))
    owner = requirements_owner(first, second)
    snap = owner.capture(replace(snap, activity_bindings=(binding.capture(), other.capture())))
    second_pub = second.capture()
    assert isinstance(second_pub.value, DirectActivityRequirementSource)
    second.publish(replace(second_pub.value.record, revision=2))
    live = owner.prepare(snap, proposed, live)
    with fence_clock(lambda: NOW):
        result = ExecutiveDecisionAuthority(owner).commit(
            proposed, snap, current=live, decision_id="direct"
        )
    assert (
        result.requirement_derivations[0].provenance.sources[0].source_id
        == first.capture().source_id
    )
    intent = proposed.intents[0]
    assert isinstance(intent.payload, ActivityIntentPayload)
    other_candidate = replace(
        proposed,
        intents=(replace(intent, payload=replace(intent.payload, binding_ref="binding-2")),),
    )
    assert owner.derive(snap, other_candidate).failure is not None


def test_selected_source_update_after_current_read_fails_fence() -> None:
    binding, _, _, snap, proposed, live = direct_fixture()
    source = source_owner(binding, (CapabilityRequirement("activity", "run"),))
    owner = requirements_owner(source)
    snap = owner.capture(snap)
    live = owner.prepare(snap, proposed, live)
    pub = source.capture()
    assert isinstance(pub.value, DirectActivityRequirementSource)
    source.publish(replace(pub.value.record, revision=2))
    with pytest.raises(FinalizationError):
        ExecutiveDecisionAuthority(owner).commit(proposed, snap, current=live, decision_id="direct")


def test_wrong_route_and_contract_are_rejected() -> None:
    with pytest.raises(ValueError):
        DirectActivityRequirementSourceSpec("route", contract_id="unknown")
    binding, _, _ = fixture()
    publish(binding)
    source = source_owner(binding, (CapabilityRequirement("activity", "run"),))
    with pytest.raises(RequirementsRejected):
        ExecutiveRequirementsOwner(BOUNDS, direct_routes={"route": {"wrong": source}})
    with pytest.raises(RequirementsRejected):
        ExecutiveRequirementsOwner(
            BOUNDS, direct_routes={"route": {"binding-1": source}, "other": {"binding-1": source}}
        )


def test_same_activity_type_selects_distinct_operations() -> None:
    from app.domain.activity_binding import BindingInputPublicationOwner, OperationInputContract
    from app.domain.plugin_registry.activity_binding import PluginActivityOperationAdapter
    from tests.domain.plugin_registry.test_plugin_registry_adjacent import available_registry

    binding, _, _, snap, proposed, live = direct_fixture()
    other = ActivityBindingAuthority(
        "inspect-binding",
        PluginActivityOperationAdapter(available_registry()),
        BindingInputPublicationOwner(
            "inspect-schema", OperationInputContract("plugin.inspect.input.v1", 1, ())
        ),
        (),
    )
    other.publish(
        revision=1,
        activity_type="activity",
        operation_ref="inspect",
        target_ref="target",
        capability_id="capability-a",
        relations=(),
    )
    owner = requirements_owner(
        source_owner(binding, (CapabilityRequirement("activity", "run"),)),
        source_owner(other, (CapabilityRequirement("activity", "inspect"),)),
    )
    snap = owner.capture(replace(snap, activity_bindings=(binding.capture(), other.capture())))
    for ref, op in (("binding-1", "run"), ("inspect-binding", "inspect")):
        intent = proposed.intents[0]
        assert isinstance(intent.payload, ActivityIntentPayload)
        candidate = replace(
            proposed,
            intents=(
                replace(
                    intent,
                    payload=replace(intent.payload, binding_ref=ref),
                    required_capabilities=(CapabilityRequirement("activity", op),),
                ),
            ),
        )
        result = owner.derive(snap, candidate)
        assert result.failure is None
        assert result.values[0].requirements.capabilities == (
            CapabilityRequirement("activity", op),
        )


def test_policy_update_and_late_source_are_rejected() -> None:
    _, _, _, snap, proposed, _ = direct_fixture()
    generation = snap.requirements_generation
    assert generation is not None
    owner = generation.owner
    owner.publish(
        replace(
            generation.policy,
            revision=2,
            rules=tuple(replace(r, policy_revision=2) for r in generation.policy.rules),
        )
    )
    assert owner.derive(snap, proposed).failure is not None
    with pytest.raises(RequirementsRejected):
        owner.publish(owner.current_generation().policy, generation.sources)


def test_source_bounds_and_empty_preconditions() -> None:
    binding, _, _ = fixture()
    publish(binding)
    source = source_owner(binding, (CapabilityRequirement("activity", "run"),))
    pub = source.capture()
    assert isinstance(pub.value, DirectActivityRequirementSource)
    assert pub.value.record.preconditions == ()
    too_small = replace(BOUNDS, executive=replace(BOUNDS.executive, max_fact_payload_json_bytes=1))
    small = DirectActivityRequirementsOwner(source.owner_id, binding, too_small)
    with pytest.raises((ValueError, FinalizationError)):
        small.publish(pub.value.record)
    conditions = tuple(
        ExecutivePreconditionRequirement(f"condition-{i}", True)
        for i in range(BOUNDS.executive.max_refs_per_intent)
    )
    with pytest.raises(RequirementsRejected):
        source.publish(replace(pub.value.record, revision=2, preconditions=conditions))


@pytest.mark.parametrize("change", ["missing", "expected"])
def test_explicit_preconditions_cannot_be_changed(change: str) -> None:
    binding, _, _, snap, proposed, live = direct_fixture()
    condition = ExecutivePreconditionRequirement("pre-turn", "available")
    owner = requirements_owner(
        source_owner(binding, (CapabilityRequirement("activity", "run"),), (condition,))
    )
    snap = owner.capture(snap)
    intent = replace(
        proposed.intents[0],
        preconditions=() if change == "missing" else (replace(condition, expected=False),),
    )
    proposed = replace(proposed, intents=(intent,))
    live = owner.prepare(snap, proposed, live)
    with pytest.raises(RequirementsRejected):
        ExecutiveDecisionAuthority(owner).commit(proposed, snap, current=live, decision_id="direct")


def test_missing_source_and_concurrent_request_capture() -> None:
    from app.domain.executive import ExecutiveIntentRequirementsPolicy

    _, _, _, snap, proposed, _ = direct_fixture()
    missing = ExecutiveRequirementsOwner(BOUNDS)
    missing.publish(ExecutiveIntentRequirementsPolicy("empty", 1, ()))
    with pytest.raises(RequirementsRejected):
        missing.capture(snap)
    assert snap.requirements_generation is not None
    owner = snap.requirements_generation.owner
    shared = owner.current_generation()
    first, second = owner.capture(snap), owner.capture(snap)
    assert owner.current_generation() is shared
    assert first.requirements_generation is not second.requirements_generation
    assert owner.derive(first, proposed).failure is None
    assert owner.derive(second, proposed).failure is None


def test_constraint_reference_still_requires_context_membership() -> None:
    _, _, _, snap, proposed, live = direct_fixture()
    intent = proposed.intents[0]
    assert isinstance(intent.payload, ActivityIntentPayload)
    proposed = replace(
        proposed,
        intents=(
            replace(
                intent, payload=replace(intent.payload, constraint_refs=("unregistered-fact",))
            ),
        ),
    )
    assert snap.requirements_generation is not None
    owner = snap.requirements_generation.owner
    live = owner.prepare(snap, proposed, live)
    with pytest.raises(ValueError):
        ExecutiveDecisionAuthority(owner).commit(proposed, snap, current=live, decision_id="direct")
