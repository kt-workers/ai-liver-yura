"""3 findingのOwner境界・provider非依存性・補助要件を確認する。"""

from dataclasses import replace
from threading import Event

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
from app.domain.activity_binding.authority import _BindingCommit
from app.domain.activity_binding.ports import ActivityOperation
from app.domain.activity_binding.projector import direct_invocation, plan_execution_inputs
from app.domain.contracts import CapabilityAvailability, CapabilityDescriptor, CapabilityRequirement
from app.domain.contracts.finalization import (
    AuthorityFinalizationFence,
    AuthorityFinalizationParticipant,
    AuthorityFinalizationRequest,
    AuthorityFinalizationResult,
    AuthorityReadPublication,
    FinalizationError,
    FinalizationFailure,
)
from tests.domain.activity_binding.test_review_capacity import publication
from tests.helpers.executive_requirements import fence_clock, make_authority


class OperationOwner:
    """試験で操作宣言自体を所有する非Plugin Owner。別Ownerのコピーではない。"""

    def __init__(self, activity: str = "activity", operation: str = "run") -> None:
        self.finalization_participant = AuthorityFinalizationParticipant(self, "foundation-op", 5)
        self.value = ActivityOperation(
            CapabilityDescriptor(
                "generic-cap", activity, (operation,), CapabilityAvailability.AVAILABLE, 1, {}
            ),
            operation,
            "generic-input",
        )

    def operation_publication(
        self, capability_id: str, operation_ref: str
    ) -> AuthorityReadPublication[ActivityOperation]:
        with self.finalization_participant:
            assert capability_id == self.value.descriptor.capability_id
            assert operation_ref == self.value.operation_ref
            return AuthorityReadPublication(self.value, (self.finalization_participant.token(),))


def test_plugin_adapter_uses_registry_native_publication() -> None:
    from app.domain.plugin_registry.activity_binding import PluginActivityOperationAdapter
    from tests.domain.plugin_registry.test_plugin_registry_adjacent import available_registry

    registry = available_registry()
    adapter = PluginActivityOperationAdapter(registry)
    publication = adapter.operation_publication("capability-a", "run")
    assert adapter.finalization_participant is registry.finalization_participant
    assert publication.tokens == registry.capability_publication().tokens
    assert publication.value.input_schema_ref == "plugin.run.input.v1"
    with pytest.raises(ValueError):
        adapter.operation_publication("capability-a", "unknown")
    with registry.finalization_participant.mutation():
        pass
    from app.domain.activity_binding.contracts import require_current

    with pytest.raises(FinalizationError):
        require_current(publication.tokens)


def test_nonplugin_operation_change_invalidates_binding() -> None:
    owner, _ = generic_owner()
    publication = publish_generic(owner)
    with owner.operation_owner.finalization_participant.mutation():
        pass
    with pytest.raises(FinalizationError):
        publication.require_current()


def generic_owner(
    count: int = 1, *, planning: bool = False
) -> tuple[ActivityBindingAuthority, ArgumentSourceOwner]:
    operation = OperationOwner("research", "collect") if planning else OperationOwner()
    schema = BindingInputPublicationOwner(
        "schema",
        OperationInputContract(
            "generic-input", 1, tuple((f"arg-{i}", ArgumentKind.STRING) for i in range(count))
        ),
    )
    source = ArgumentSourceOwner(
        "actual",
        tuple(
            ArgumentSourceFact(f"fact-{i}", "actual", 1, "generic-input", f"値-{i}")
            for i in range(count)
        ),
    )
    return ActivityBindingAuthority("generic-binding", operation, schema, (source,)), source


def publish_generic(
    owner: ActivityBindingAuthority, count: int = 1, *, planning: bool = False
) -> ActivityExecutionBindingPublication:
    return owner.publish(
        revision=1,
        activity_type="research" if planning else "activity",
        operation_ref="collect" if planning else "run",
        target_ref="target-1",
        capability_id="generic-cap",
        relations=tuple(ArgumentSourceRelation(f"arg-{i}", f"fact-{i}") for i in range(count)),
    )


def test_same_owner_many_facts_share_native_token_and_invalidate_together() -> None:
    owner, source = generic_owner(20)
    first = publish_generic(owner, 20)
    sibling = ActivityBindingAuthority("sibling", owner.operation_owner, owner.schema, (source,))
    second = publish_generic(sibling, 20)
    assert len(first.value.sources) == 20
    assert len({t._participant for t in first.tokens}) == 4
    assert first.tokens[-1]._participant is source.finalization_participant
    assert second.tokens[-1] == first.tokens[-1]
    source.publish(tuple(replace(f, revision=2, value="更新") for f in source.capture().value))
    for pub in (first, second):
        with pytest.raises(FinalizationError):
            pub.require_current()


@pytest.mark.parametrize("total", [15, 16, 17])
def test_binding_publication_obeys_fence_capacity(total: int) -> None:
    if total <= 16:
        pub = publication(total - 3, "publication-capacity", "target")
        assert len({t._participant for t in pub.tokens}) == total
    else:
        with pytest.raises(FinalizationError) as caught:
            publication(total - 3, "publication-capacity", "target")
        assert caught.value.failure is FinalizationFailure.INVALID_LOCK_CONFIGURATION


def test_binding_fence_rejects_source_update_without_replacing_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    owner, source = generic_owner()
    old = publish_generic(owner)
    original = AuthorityFinalizationFence.finalize

    def changed(
        self: AuthorityFinalizationFence,
        request: AuthorityFinalizationRequest[_BindingCommit, ActivityExecutionBindingPublication],
        *,
        cancellation: Event | None = None,
    ) -> AuthorityFinalizationResult[ActivityExecutionBindingPublication]:
        source.publish(tuple(replace(f, revision=2, value="変更") for f in source.capture().value))
        return original(self, request, cancellation=cancellation)

    monkeypatch.setattr(AuthorityFinalizationFence, "finalize", changed)
    with pytest.raises(FinalizationError) as caught:
        publish_generic(owner)
    assert caught.value.failure is FinalizationFailure.GENERATION_MISMATCH
    assert owner._publication is old
    with pytest.raises(FinalizationError):
        old.require_current()
    with pytest.raises(FinalizationError):
        owner.capture()


def test_independent_owners_keep_distinct_native_participants() -> None:
    owner, source = generic_owner()
    other = ArgumentSourceOwner(
        "other", (ArgumentSourceFact("other-fact", "other", 1, "generic-input", "別値"),)
    )
    schema = BindingInputPublicationOwner(
        "schema-2",
        OperationInputContract(
            "generic-input", 1, (("a", ArgumentKind.STRING), ("b", ArgumentKind.STRING))
        ),
    )
    binding = ActivityBindingAuthority("two-owners", owner.operation_owner, schema, (source, other))
    pub = binding.publish(
        revision=1,
        activity_type="activity",
        operation_ref="run",
        target_ref="target-1",
        capability_id="generic-cap",
        relations=(
            ArgumentSourceRelation("a", "fact-0"),
            ArgumentSourceRelation("b", "other-fact"),
        ),
    )
    participants = {t._participant for t in pub.tokens}
    assert source.finalization_participant is not other.finalization_participant
    assert {source.finalization_participant, other.finalization_participant} <= participants


def test_capacity_rejection_leaves_binding_unpublished(monkeypatch: pytest.MonkeyPatch) -> None:

    original = AuthorityFinalizationFence.finalize
    seen: list[AuthorityFinalizationParticipant] = []

    def record(
        self: AuthorityFinalizationFence,
        request: AuthorityFinalizationRequest[_BindingCommit, ActivityExecutionBindingPublication],
        *,
        cancellation: Event | None = None,
    ) -> AuthorityFinalizationResult[ActivityExecutionBindingPublication]:
        seen.append(request.target)
        return original(self, request, cancellation=cancellation)

    monkeypatch.setattr(AuthorityFinalizationFence, "finalize", record)
    with pytest.raises(FinalizationError):
        publication(14, "too-many", "target")
    assert len(seen) == 1
    # 登録済みの確定操作へ進入しないため、入口で失効した1世代だけが残る。
    assert seen[0].token().generation == 1


@pytest.mark.parametrize("count", [1, 20])
@pytest.mark.parametrize("fault", ["none", "missing", "stale", "unavailable"])
def test_nonplugin_direct_with_authoritative_auxiliary(
    monkeypatch: pytest.MonkeyPatch, fault: str, count: int
) -> None:
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
    from app.domain.plugin_registry.authority import PluginRegistryAuthority
    from tests.domain.executive.test_executive import NOW, candidate, live_state, snapshot

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("非Plugin経路でRegistryを生成してはいけません")

    monkeypatch.setattr(PluginRegistryAuthority, "__init__", forbidden)
    owner, _ = generic_owner(count)
    pub = publish_generic(owner, count)
    auxiliary = CapabilityDescriptor(
        "network", "network", ("access",), CapabilityAvailability.AVAILABLE, 1, {}
    )
    requirements = (
        CapabilityRequirement("activity", "run"),
        CapabilityRequirement("network", "access"),
    )
    rules = ExecutiveRequirementsOwner(V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)
    rules.publish(
        ExecutiveIntentRequirementsPolicy(
            "policy",
            1,
            (
                ExecutiveIntentRequirementRule(
                    "rule",
                    1,
                    "policy",
                    1,
                    ExecutiveIntentKind.ACTIVITY,
                    RequirementSelector(),
                    RequirementMode.CONSTANT,
                    requirements,
                    (),
                ),
            ),
        )
    )
    initial = snapshot()
    snap = rules.capture(
        replace(
            initial,
            requirements_generation=None,
            capabilities=(pub.descriptor, auxiliary),
            activity_bindings=(pub,),
            facts=(
                *initial.facts,
                ExecutiveFactRef("target-1", ExecutiveFactKind.ENVIRONMENT, 1, {}),
            ),
        )
    )
    intent = ExecutiveIntent(
        "direct",
        ExecutiveIntentKind.ACTIVITY,
        "選択済みの活動",
        ActivityIntentPayload("activity", "target-1", (), "generic-binding"),
        required_capabilities=requirements,
    )
    proposed = replace(candidate(), outcome=ExecutiveOutcome.ACT, intents=(intent,))
    caps: tuple[CapabilityDescriptor, ...] = (pub.descriptor, auxiliary)
    if fault == "missing":
        caps = (pub.descriptor,)
    elif fault == "stale":
        caps = (pub.descriptor, replace(auxiliary, revision=2))
    elif fault == "unavailable":
        caps = (pub.descriptor, replace(auxiliary, availability=CapabilityAvailability.UNAVAILABLE))
    live = rules.prepare(
        snap, proposed, replace(live_state(), capabilities=caps, activity_bindings=(pub,))
    )
    authority = make_authority(snap)
    with fence_clock(lambda: NOW):
        if fault != "none":
            with pytest.raises(ValueError):
                authority.commit(proposed, snap, current=live, decision_id="aux")
            assert not authority.has_committed(snap.trigger_id)
        else:
            committed = authority.commit(proposed, snap, current=live, decision_id="aux")
            invocation = direct_invocation(
                committed,
                intent,
                command_id="command",
                invocation_id="invocation",
                requested_at=NOW,
            )
            assert invocation.command.required_capabilities == requirements
            assert invocation.operation_ref == "run"


def test_nonplugin_plan_selection_and_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.domain.contracts import PreconditionRef
    from app.domain.goal_planning import GoalPlanningAuthority
    from app.domain.plugin_registry.authority import PluginRegistryAuthority
    from tests.domain.goal_planning import test_goal_planning as fixtures

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("非Plugin経路でRegistryを生成してはいけません")

    monkeypatch.setattr(PluginRegistryAuthority, "__init__", forbidden)
    binding_owner, _ = generic_owner(planning=True)
    pub = publish_generic(binding_owner, planning=True)
    monkeypatch.setattr(fixtures, "planning_binding", lambda: pub)
    owner = GoalPlanningAuthority()
    plan = owner.commit(
        fixtures.candidate(),
        fixtures.context(),
        fixtures.current(),
        plan_id="generic-plan",
        committed_at=fixtures.NOW,
    )
    bindings, facts = plan_execution_inputs(
        plan, owner, (PreconditionRef("pre-ready", "equals", "target-1", True),)
    )
    assert bindings[0].arguments == {"arg-0": "値-0"}
    assert facts[0].reference_id == "fact-0"
