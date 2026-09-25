"""本体の読取境界が選択された正規bindingだけを再取得することを確認する。"""

from types import SimpleNamespace
from typing import cast

import pytest

from app.composition.execution import CoreExecutionDelivery
from app.composition.execution_configuration import _ExecutionEvidence
from app.composition.executive import CoreExecutiveEvidence
from app.domain.activity_binding import ActivityBindingAuthority
from app.domain.attention import AttentionPriority, AttentionSource, AttentionSourceKind
from app.domain.contracts import CapabilityRequirement
from app.domain.contracts.finalization import FinalizationError
from app.domain.executive import (
    AuthoritativeIntentRequirements,
    ExecutiveContextSnapshot,
    ExecutiveDecisionCandidate,
    RequirementsRejected,
)
from tests.domain.activity_binding.test_binding import direct_fixture, fixture, publish
from tests.domain.executive.test_executive import NOW
from tests.helpers.direct_activity_requirements import requirements_owner, source_owner


@pytest.mark.asyncio
async def test_current_read_ignores_unselected_closed_binding() -> None:
    binding, _, _, snapshot, candidate, _ = direct_fixture()
    other_base, schema, argument = fixture()
    other = ActivityBindingAuthority("other", other_base.operation_owner, schema, (argument,))
    publish(other)
    owner = requirements_owner(
        source_owner(binding, (CapabilityRequirement("activity", "run"),)),
        source_owner(other, (CapabilityRequirement("activity", "run"),)),
    )
    source = AttentionSource(
        "event", AttentionSourceKind.USER_INTERACTION, AttentionPriority.NORMAL, 1, NOW, NOW
    )

    class Base:
        async def read(self, source: AttentionSource) -> CoreExecutiveEvidence:
            return CoreExecutiveEvidence(source, (), None, (), (), ())

        async def requirements_for(
            self, snapshot: ExecutiveContextSnapshot, candidate: ExecutiveDecisionCandidate
        ) -> tuple[AuthoritativeIntentRequirements, ...]:
            result = owner.derive(snapshot, candidate)
            assert result.failure is None
            return tuple(item.requirements for item in result.values)

    execution = cast(CoreExecutionDelivery, SimpleNamespace(_plan_events={}, _scope_events={}))
    reader = _ExecutionEvidence(Base(), (binding, other), execution, owner)
    initial = await reader.read(source)
    assert len(initial.activity_bindings) == 2
    other.close()
    current = await reader.read_for_candidate(source, candidate)
    assert current.activity_bindings == (binding.capture(),)
    with pytest.raises(FinalizationError):
        await reader.read(source)


def test_composition_requires_same_registered_binding_owner() -> None:
    binding, _, _ = fixture()
    publish(binding)
    owner = requirements_owner(source_owner(binding, (CapabilityRequirement("activity", "run"),)))
    owner.require_binding_owners((binding,))
    duplicate_identity, _, _ = fixture()
    publish(duplicate_identity)
    with pytest.raises(RequirementsRejected):
        owner.require_binding_owners((duplicate_identity,))
