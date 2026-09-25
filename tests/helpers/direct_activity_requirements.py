"""試験が明示した要件を実際のDirect Ownerへ登録する。"""

from app.domain.activity_binding import ActivityBindingAuthority
from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY as BOUNDS
from app.domain.contracts import CapabilityRequirement
from app.domain.executive import (
    DirectActivityRequirementRecord,
    DirectActivityRequirementSourceSpec,
    DirectActivityRequirementsOwner,
    ExecutiveIntentKind,
    ExecutiveIntentRequirementRule,
    ExecutiveIntentRequirementsPolicy,
    ExecutivePreconditionRequirement,
    ExecutiveRequirementsOwner,
    RequirementMode,
    RequirementSelector,
)
from app.domain.executive.direct_activity_requirements import DIRECT_ACTIVITY_REQUIREMENTS_CONTRACT


def source_owner(
    binding: ActivityBindingAuthority,
    capabilities: tuple[CapabilityRequirement, ...],
    preconditions: tuple[ExecutivePreconditionRequirement, ...] = (),
) -> DirectActivityRequirementsOwner:
    owner = DirectActivityRequirementsOwner("requirements-" + binding.binding_id, binding, BOUNDS)
    value = binding.capture().value
    owner.publish(
        DirectActivityRequirementRecord(
            owner.owner_id,
            DIRECT_ACTIVITY_REQUIREMENTS_CONTRACT,
            "record-" + binding.binding_id,
            1,
            value.binding_id,
            value.revision,
            value.activity_type,
            value.target_ref,
            capabilities,
            preconditions,
        )
    )
    return owner


def requirements_owner(*sources: DirectActivityRequirementsOwner) -> ExecutiveRequirementsOwner:
    owner = ExecutiveRequirementsOwner(
        BOUNDS, direct_routes={"activities": {s.binding.binding_id: s for s in sources}}
    )
    owner.publish(
        ExecutiveIntentRequirementsPolicy(
            "direct-policy",
            1,
            (
                ExecutiveIntentRequirementRule(
                    "direct-rule",
                    1,
                    "direct-policy",
                    1,
                    ExecutiveIntentKind.ACTIVITY,
                    RequirementSelector(),
                    RequirementMode.UPSTREAM,
                    source=DirectActivityRequirementSourceSpec("activities"),
                ),
            ),
        )
    )
    return owner
