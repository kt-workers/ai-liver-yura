"""試験の信頼済み構成へ明示的な必須要件方針を登録する。"""

from dataclasses import replace

from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
from app.domain.contracts import CapabilityRequirement
from app.domain.contracts.finalization import AuthorityFinalizationParticipant
from app.domain.executive import (
    ExecutiveContextSnapshot,
    ExecutiveDecisionAuthority,
    ExecutiveIntentKind,
    ExecutiveIntentRequirementRule,
    ExecutiveIntentRequirementsPolicy,
    ExecutivePreconditionRequirement,
    ExecutiveRequirementsOwner,
    RequirementMode,
    RequirementSelector,
    RequirementSourcePublication,
)
from app.domain.executive.requirements import SourceValue


def speech_owner() -> ExecutiveRequirementsOwner:
    owner = ExecutiveRequirementsOwner(V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)
    owner.publish(
        ExecutiveIntentRequirementsPolicy(
            "test-requirements",
            1,
            (
                ExecutiveIntentRequirementRule(
                    "speech",
                    1,
                    "test-requirements",
                    1,
                    ExecutiveIntentKind.SPEECH,
                    RequirementSelector(),
                    RequirementMode.CONSTANT,
                    (CapabilityRequirement("speech", "prepare"),),
                    (ExecutivePreconditionRequirement("pre-turn", "available"),),
                ),
            ),
        )
    )
    return owner


SPEECH_OWNER = speech_owner()


def make_authority(context: ExecutiveContextSnapshot | None = None) -> ExecutiveDecisionAuthority:
    owner = (
        SPEECH_OWNER
        if context is None or context.requirements_generation is None
        else context.requirements_generation.owner
    )
    return ExecutiveDecisionAuthority(owner)


class PlanSources:
    """単体試験の不変な計画範囲と完了評価文脈を保持する所有者。"""

    def __init__(self) -> None:
        self.participant = AuthorityFinalizationParticipant(self, "test-plan-sources", 15)


def capture_plans(
    context: ExecutiveContextSnapshot,
    sources: tuple[RequirementSourcePublication, ...] | None = None,
) -> ExecutiveContextSnapshot:
    owner = ExecutiveRequirementsOwner(V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)
    if sources is None:
        fixture_owner = PlanSources()
        values: tuple[SourceValue, ...] = (*context.plan_scopes, *context.plan_progress_contexts)
        sources = tuple(
            RequirementSourcePublication(
                f"plan-source-{i}", 1, value, (fixture_owner.participant.token(),)
            )
            for i, value in enumerate(values)
        )
    rules = tuple(
        ExecutiveIntentRequirementRule(
            kind.value,
            1,
            "test-plan-requirements",
            1,
            kind,
            RequirementSelector(),
            mode,
        )
        for kind, mode in (
            (ExecutiveIntentKind.PLAN_EXECUTION, RequirementMode.PLAN_SCOPE),
            (ExecutiveIntentKind.PLAN_PROGRESS, RequirementMode.CONSTANT),
        )
    )
    owner.publish(ExecutiveIntentRequirementsPolicy("test-plan-requirements", 1, rules), sources)
    return owner.capture(replace(context, requirements_generation=None))
