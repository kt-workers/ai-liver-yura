from app.domain.autonomous_continuation import (
    AutonomousContinuationAction,
    AutonomousContinuationEvaluation,
)
from app.domain.causal_diagnostics import (
    CausalDecisionOutcome,
    CausalDecisionStage,
    RouteLifecycle,
)
from app.domain.character_response import (
    ActivityExecutionStatus,
    CharacterResponse,
    ResponseClaim,
    ResponseContext,
)
from app.domain.interaction_intention import (
    InteractionIntention,
    InteractionIntentionType,
)
from app.runtime.causal_decision_observer import CausalDecisionObserver
from app.runtime.legacy_route_inventory import LegacyRouteInventory
from app.runtime.response_claim_validator import (
    DeterministicFactValidator,
    IndependentClaimExtractor,
)


def act_intention() -> InteractionIntention:
    return InteractionIntention(
        intention=InteractionIntentionType.ACT,
        confidence=0.95,
        source="test",
        reason="body_action_requested",
        activity_type="avatar_body_action",
        observation_only=True,
    )


def response_context(
    *,
    status: ActivityExecutionStatus,
    activity_type: str,
    allowed: tuple[ResponseClaim, ...],
    forbidden: tuple[ResponseClaim, ...],
) -> ResponseContext:
    return ResponseContext(
        user_input="右手を挙げてみて",
        activity_type=activity_type,
        operation="perform",
        status=status,
        failure_reason=None,
        result_summary="",
        allowed_claims=allowed,
        forbidden_claims=forbidden,
        activity_goal="身体表現を行う",
        memory={"interaction_intention": act_intention().as_context()},
    )


def test_unexecuted_embodied_completion_claim_is_rejected() -> None:
    context = response_context(
        status=ActivityExecutionStatus.WAITING_INPUT,
        activity_type="conversation",
        allowed=(ResponseClaim.CONVERSATION_ONLY, ResponseClaim.ACTIVITY_REQUESTED),
        forbidden=(
            ResponseClaim.ACTIVITY_COMPLETED,
            ResponseClaim.ACTIVITY_SUCCEEDED,
            ResponseClaim.EXTERNAL_RESULT_OBTAINED,
        ),
    )
    response = CharacterResponse(
        speech="はい、右手を挙げたよ！",
        claims=(ResponseClaim.CONVERSATION_ONLY,),
    )
    extractor = IndependentClaimExtractor()

    claims = extractor.extract(context, response.speech)
    result = DeterministicFactValidator().validate(context, response, claims)

    assert any(
        claim.claim_type.value == "activity_succeeded" for claim in claims
    )
    assert result.accepted is False
    assert result.reason == "embodied_action_claim_without_execution_result"


def test_future_embodied_expression_is_not_completion_claim() -> None:
    context = response_context(
        status=ActivityExecutionStatus.WAITING_INPUT,
        activity_type="conversation",
        allowed=(ResponseClaim.CONVERSATION_ONLY, ResponseClaim.ACTIVITY_REQUESTED),
        forbidden=(
            ResponseClaim.ACTIVITY_COMPLETED,
            ResponseClaim.ACTIVITY_SUCCEEDED,
            ResponseClaim.EXTERNAL_RESULT_OBTAINED,
        ),
    )
    response = CharacterResponse(
        speech="よーし、右手を挙げてみるね！",
        claims=(ResponseClaim.CONVERSATION_ONLY,),
    )
    extractor = IndependentClaimExtractor()

    claims = extractor.extract(context, response.speech)
    result = DeterministicFactValidator().validate(context, response, claims)

    assert claims == ()
    assert result.accepted is True


def test_executed_embodied_completion_claim_is_allowed() -> None:
    context = response_context(
        status=ActivityExecutionStatus.SUCCEEDED,
        activity_type="avatar_body_action",
        allowed=(
            ResponseClaim.ACTIVITY_COMPLETED,
            ResponseClaim.ACTIVITY_SUCCEEDED,
        ),
        forbidden=(
            ResponseClaim.ACTIVITY_FAILED,
            ResponseClaim.ACTIVITY_REJECTED,
        ),
    )
    response = CharacterResponse(
        speech="はい、右手を挙げたよ！",
        claims=(ResponseClaim.ACTIVITY_SUCCEEDED,),
    )
    extractor = IndependentClaimExtractor()

    claims = extractor.extract(context, response.speech)
    result = DeterministicFactValidator().validate(context, response, claims)

    assert result.accepted is True
    assert result.reason == "deterministic_facts_valid"


def test_legacy_route_inventory_classifies_body_command_driver_as_deprecated() -> None:
    route = LegacyRouteInventory.get("user_body_command_as_primary_motion_driver")

    assert route.lifecycle is RouteLifecycle.DEPRECATED
    assert route.removable is True
    assert route.replacement == "state_driven_body_pose_runtime"


def test_active_and_compatibility_routes_are_explicitly_separated() -> None:
    active = {
        route.name
        for route in LegacyRouteInventory.all()
        if route.lifecycle is RouteLifecycle.ACTIVE
    }
    compatibility = {
        route.name
        for route in LegacyRouteInventory.all()
        if route.lifecycle is RouteLifecycle.COMPATIBILITY
    }

    assert "interaction_intention_appraisal" in active
    assert "autonomous_topic_evaluate_completion" in active
    assert "drive_should_start_autonomous_talk" in compatibility
    assert "autonomous_topic_should_complete_tuple" in compatibility
    assert active.isdisjoint(compatibility)


def test_causal_observer_records_finite_continuation_snapshot() -> None:
    observer = CausalDecisionObserver()
    evaluation = AutonomousContinuationEvaluation(
        action=AutonomousContinuationAction.COMPLETE,
        reason="user_response_expected_after_question",
        continuation_strength=0.72,
        turn_count=1,
        waiting_for_user=True,
    )

    snapshot = observer.observe_autonomous_continuation(evaluation)
    context = snapshot.as_context()

    assert snapshot.stage is CausalDecisionStage.AUTONOMOUS_CONTINUATION
    assert snapshot.outcome is CausalDecisionOutcome.COMPLETE
    assert context["legacy_route"]["lifecycle"] == "compatibility"
    assert context["causal_route"]["lifecycle"] == "active"
    assert context["metrics"]["waiting_for_user"] is True
    assert "user_text" not in context
    assert "speech" not in context
    assert "prompt" not in context
