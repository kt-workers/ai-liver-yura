"""共通Routerから判断根拠への機械投影と、空実測の拒否境界を検証する。"""

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

import pytest

from app.composition.executive import CoreExecutiveBinding
from app.composition.executive_requirements import (
    CoreExecutiveRequirementsReader,
    CorePreconditionSourceReader,
    build_core_executive_input_evidence,
)
from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY as BOUNDS
from app.domain.contracts.common import JsonValue, freeze_json
from app.domain.contracts.finalization import (
    AuthorityFinalizationParticipant,
    AuthorityReadPublication,
)
from app.domain.contracts.preconditions import (
    PreconditionFailure,
    PreconditionObservation,
    PreconditionReadError,
    PreconditionSourceBinding,
    PreconditionSourceRef,
    PreconditionSourceRegistration,
    PreconditionSourceRouter,
)
from app.domain.executive import ExecutivePreconditionRequirement, RequirementsRejected
from app.domain.llm import LLMRoleRequest, LLMRoleResult, StructuredPayload
from tests.domain.executive.test_executive import policy
from tests.system_integration.test_core_executive_requirements import (
    GoalPort,
    deliberate,
    production,
)

SOURCE = PreconditionSourceRef("明示した試験Owner", "試験の実測公開")
BINDING = PreconditionSourceBinding("試験条件", "試験対象", "試験の述語", SOURCE)


class ActualOwner:
    """試験専用の状態を所有し、同じ読取で値とtokenを公開する。"""

    def __init__(self) -> None:
        self.participant = AuthorityFinalizationParticipant(self, SOURCE.owner_id, 10)
        self.actual: JsonValue = True
        self.old: AuthorityReadPublication[PreconditionObservation] | None = None
        self.fail = False
        self.last: AuthorityReadPublication[PreconditionObservation] | None = None

    async def read_current(
        self, binding: PreconditionSourceBinding
    ) -> AuthorityReadPublication[PreconditionObservation]:
        if self.fail:
            raise RuntimeError("試験供給元の失敗")
        if self.old is not None:
            return self.old
        with self.participant:
            self.last = AuthorityReadPublication(
                PreconditionObservation(binding, self.actual), (self.participant.token(),)
            )
            return self.last

    def router(self) -> PreconditionSourceRouter:
        return PreconditionSourceRouter(
            (PreconditionSourceRegistration(SOURCE, self, self.participant),)
        )


@pytest.mark.asyncio
async def test_projection_preserves_all_identity_actual_and_same_tokens() -> None:
    value = await production()
    owner = ActualOwner()
    owner.actual = freeze_json({"nested": [False, 1, "1", None]})
    reader = CorePreconditionSourceReader(owner.router(), (BINDING,), BOUNDS)
    facts = await reader.preconditions_for(value.dispatch.selected_source)
    assert len(facts) == 1
    fact = facts[0].value
    assert (fact.precondition_id, fact.subject_ref, fact.predicate) == (
        BINDING.precondition_id,
        BINDING.subject_ref,
        BINDING.predicate,
    )
    assert fact.actual == owner.actual
    assert owner.last is not None
    assert facts[0].tokens is owner.last.tokens


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["unregistered", "unavailable", "stale"])
async def test_router_failure_is_not_empty_success(mode: str) -> None:
    value = await production()
    owner = ActualOwner()
    router = owner.router()
    expected = PreconditionFailure.SOURCE_UNAVAILABLE
    if mode == "unregistered":
        router = PreconditionSourceRouter(())
        expected = PreconditionFailure.UNREGISTERED_SOURCE
    elif mode == "unavailable":
        owner.fail = True
    else:
        owner.old = await owner.read_current(BINDING)
        with owner.participant.mutation():
            owner.actual = False
        expected = PreconditionFailure.STALE_PUBLICATION
    adapter = CorePreconditionSourceReader(router, (BINDING,), BOUNDS)
    with pytest.raises(PreconditionReadError) as error:
        await adapter.preconditions_for(value.dispatch.selected_source)
    assert error.value.failure is expected
    reader = CoreExecutiveRequirementsReader(value.owner, adapter, BOUNDS)
    with pytest.raises(RequirementsRejected):
        await reader.preconditions_for(value.dispatch.selected_source)


class ConditionPort(GoalPort):
    def __init__(self, conditions: tuple[ExecutivePreconditionRequirement, ...]) -> None:
        super().__init__()
        self.conditions = conditions

    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
        result = await super().invoke(request)
        assert result.output is not None and isinstance(result.output.value, Mapping)
        payload: dict[str, Any] = dict(result.output.value)
        intent = dict(payload["intents"][0])
        intent["preconditions"] = [condition.to_dict() for condition in self.conditions]
        payload["intents"] = [intent]
        return replace(
            result, output=StructuredPayload(result.output.schema_id, freeze_json(payload))
        )


async def connected(required: bool, measured: bool) -> Any:
    value = await production()
    conditions = (
        (ExecutivePreconditionRequirement(BINDING.precondition_id, True),) if required else ()
    )
    generation = value.owner.current_generation()
    value.owner.publish(
        replace(
            generation.policy,
            revision=2,
            rules=tuple(
                replace(rule, preconditions=conditions, revision=2, policy_revision=2)
                for rule in generation.policy.rules
            ),
        )
    )
    value.actual_owner = ActualOwner()
    value.adapter = CorePreconditionSourceReader(
        value.actual_owner.router(), (BINDING,) if measured else (), BOUNDS
    )
    value.requirements = CoreExecutiveRequirementsReader(value.owner, value.adapter, BOUNDS)
    value.reader = build_core_executive_input_evidence(
        value.inputs, value.core.connection, value.registry, value.requirements
    )
    value.port = ConditionPort(conditions)
    value.binding = CoreExecutiveBinding(
        value.attention, value.reader, value.port, policy(), value.authority, value.core.clock
    )
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "required,measured", [(True, True), (True, False), (False, False), (False, True)]
)
async def test_real_adapter_and_executive_required_vs_measured(
    required: bool, measured: bool
) -> None:
    value = await connected(required, measured)
    facts = await value.adapter.preconditions_for(value.dispatch.selected_source)
    assert len(facts) == int(measured)
    if required and not measured:
        with pytest.raises(ValueError, match="intent precondition is outside snapshot"):
            await deliberate(value)
        assert not value.authority.has_committed(value.dispatch.trigger.trigger_id)
        assert value.binding.latest_decision() is None
    else:
        decision = await deliberate(value)
        assert bool(decision.validated_preconditions) == required
        tokens = [t for t in decision.evidence_tokens if t.owner_identity == SOURCE.owner_id]
        assert bool(tokens) == required
        if required:
            assert value.actual_owner.last is not None
            assert tokens == list(value.actual_owner.last.tokens)


def test_bounded_unique_binding_configuration() -> None:
    owner = ActualOwner()
    with pytest.raises(RequirementsRejected):
        CorePreconditionSourceReader(owner.router(), (BINDING, BINDING), BOUNDS)
    bindings = tuple(
        replace(BINDING, precondition_id=f"p{i}")
        for i in range(BOUNDS.executive.max_precondition_facts + 1)
    )
    with pytest.raises(RequirementsRejected):
        CorePreconditionSourceReader(owner.router(), bindings, BOUNDS)


@pytest.mark.asyncio
async def test_zero_bindings_does_not_hide_unregistered_policy() -> None:
    from app.domain.executive import ExecutiveRequirementsOwner

    value = await connected(False, False)
    value.requirements.owner = ExecutiveRequirementsOwner(BOUNDS)
    with pytest.raises(RequirementsRejected):
        await deliberate(value)
    assert not value.authority.has_committed(value.dispatch.trigger.trigger_id)


@pytest.mark.asyncio
async def test_adapter_cancellation_reaps_router_reader() -> None:
    import asyncio

    started, released = asyncio.Event(), asyncio.Event()

    class WaitingOwner(ActualOwner):
        async def read_current(
            self, binding: PreconditionSourceBinding
        ) -> AuthorityReadPublication[PreconditionObservation]:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                released.set()
            return await super().read_current(binding)

    value = await production()
    owner = WaitingOwner()
    adapter = CorePreconditionSourceReader(owner.router(), (BINDING,), BOUNDS)
    before = asyncio.all_tasks()
    task = asyncio.create_task(adapter.preconditions_for(value.dispatch.selected_source))
    await started.wait()
    task.cancel()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert released.is_set()
    assert asyncio.all_tasks() == before
