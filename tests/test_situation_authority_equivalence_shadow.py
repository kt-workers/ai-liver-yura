from __future__ import annotations

from app.domain.behavior import (
    ActivityAuthorityRequirement,
    ActivityDefinition,
    ActivityOperation,
    BehaviorPlanningContext,
    SituationAnalysis,
)
from app.domain.morals import (
    ActivityCandidateSemanticEquivalenceEvidence,
    ExecutionBoundaryEquivalenceStatus,
    MoralProfile,
    MoralState,
    SemanticEquivalenceDimension,
)
from app.runtime.situation_semantic_equivalence_shadow_observer import (
    SituationSemanticEquivalenceShadowObserver,
)


def _definition(activity_type: str) -> ActivityDefinition:
    return ActivityDefinition(
        activity_type=activity_type,
        display_name=activity_type,
        required_capability=None,
        provider_plugin_id="runtime",
        supported_operations=(ActivityOperation.START,),
        constraints_schema={"type": "object", "additionalProperties": False},
        authority_requirement=ActivityAuthorityRequirement(
            policy_id="core.user_conversation.v1",
            allowed_roles=("administrator", "user", "viewer"),
        ),
    )


def test_situation_shadow_observes_explicit_authority_equivalence() -> None:
    definitions = (
        _definition("autonomous_talk"),
        _definition("conversation_with_user"),
    )
    profile = MoralProfile(compassion=1.0, altruism=1.0, dominance=0.0)
    state = MoralState(
        empathy_activation=1.0,
        selfish_impulse=0.0,
        aggressive_impulse=0.0,
    )
    context = BehaviorPlanningContext(
        user_text="会話を続けて",
        source_event_id="event-authority-shadow-1",
        available_capabilities=frozenset(),
        authority_role="viewer",
        instruction_trusted=False,
        activity_definitions=definitions,
        motivation={"recommended_activity_types": []},
        moral={
            "profile": profile.as_dict(),
            "state": state.as_dict(),
            "composite": profile.compose(state).as_dict(),
            "observation_only": True,
        },
    )
    evidence = ActivityCandidateSemanticEquivalenceEvidence(
        candidate_group=(
            "autonomous_talk",
            "conversation_with_user",
        ),
        intent=SemanticEquivalenceDimension.CONFIRMED,
        operation=SemanticEquivalenceDimension.CONFIRMED,
        goal=SemanticEquivalenceDimension.CONFIRMED,
        source="situation_evaluator_llm",
        evidence_id="authority-shadow-evidence-1",
    )
    analysis = SituationAnalysis(
        activity_candidate="conversation_with_user",
        operation=ActivityOperation.START,
        goal="ユーザーと対話する",
        evaluator_type="llm",
        semantic_equivalence_evidence=evidence,
    )

    result = SituationSemanticEquivalenceShadowObserver().observe(
        context,
        analysis,
    )

    authority = result.execution_boundary_equivalence.authority
    assert authority.status is ExecutionBoundaryEquivalenceStatus.CONFIRMED
    assert authority.candidate_requirement_contract_available is True
    assert tuple(
        candidate.current_request_authorized for candidate in authority.candidates
    ) == (True, True)
    assert result.execution_boundary_equivalence.status is (
        ExecutionBoundaryEquivalenceStatus.UNCONFIRMED
    )
    assert result.activation_permitted is False
