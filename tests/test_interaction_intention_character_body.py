from dataclasses import asdict

from app.domain.activities import Activity, ActivityType
from app.domain.body import BodyPostureTendency
from app.domain.character_response import (
    ActivityExecutionStatus,
    ResponseContext,
)
from app.domain.interaction_intention import (
    InteractionIntention,
    InteractionIntentionType,
)
from app.runtime.body_activity_context_builder import BodyActivityContextBuilder
from app.runtime.interaction_expression_projector import (
    InteractionExpressionProjector,
)


def intention(
    kind: InteractionIntentionType,
    *,
    observation_only: bool = True,
) -> InteractionIntention:
    return InteractionIntention(
        intention=kind,
        confidence=0.9,
        source="test",
        reason="test_reason",
        target_type="counterpart",
        target_id="user",
        observation_only=observation_only,
    )


def response_context(
    *,
    memory: dict[str, object] | None = None,
    constraints: dict[str, object] | None = None,
) -> ResponseContext:
    return ResponseContext(
        user_input="こんにちは",
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.WAITING_INPUT,
        failure_reason=None,
        result_summary="会話を継続する",
        allowed_claims=(),
        forbidden_claims=(),
        activity_goal="会話する",
        memory=memory or {},
        constraints=constraints or {},
    )


def test_interaction_intention_round_trips_from_context() -> None:
    original = intention(InteractionIntentionType.COMFORT, observation_only=False)

    restored = InteractionIntention.from_context(original.as_context())

    assert restored == original
    assert restored is not None
    assert restored.intention is InteractionIntentionType.COMFORT
    assert restored.observation_only is False


def test_invalid_interaction_intention_context_is_rejected() -> None:
    assert InteractionIntention.from_context({"intention": "unknown"}) is None
    assert InteractionIntention.from_context({"intention": "share", "confidence": True}) is None
    assert InteractionIntention.from_context("share") is None


def test_response_context_restores_intention_from_memory() -> None:
    expected = intention(InteractionIntentionType.SHARE, observation_only=False)

    context = response_context(
        memory={"interaction_intention": expected.as_context()}
    )

    assert context.interaction_intention == expected
    serialized = asdict(context)
    assert serialized["interaction_intention"]["intention"] == (
        InteractionIntentionType.SHARE
    )


def test_response_context_restores_intention_from_safe_internal_constraint() -> None:
    expected = intention(InteractionIntentionType.ANSWER)

    context = response_context(
        constraints={"_interaction_intention": expected.as_context()}
    )

    assert context.interaction_intention == expected


def test_body_context_projects_shared_intention_without_motion_command() -> None:
    expected = intention(InteractionIntentionType.SET_BOUNDARY)
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="境界を伝える",
        context={
            "behavior_plan": {
                "constraints": {
                    "_interaction_intention": expected.as_context(),
                }
            }
        },
    )

    context = BodyActivityContextBuilder().build(activity)

    assert context.interaction_intention == expected
    assert context.posture_tendency is BodyPostureTendency.CLOSED
    assert context.attention_target == "user"
    assert context.engagement < 0.72
    assert "gesture" not in expected.as_context()
    assert "motion" not in expected.as_context()


def test_explicit_body_context_remains_highest_priority() -> None:
    expected = intention(InteractionIntentionType.SET_BOUNDARY)
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="明示身体文脈を優先する",
        context={
            "behavior_plan": {
                "constraints": {
                    "_interaction_intention": expected.as_context(),
                }
            },
            "body_context": {
                "posture_tendency": "open",
                "movement_energy": 0.91,
                "gaze_freedom": 0.77,
                "engagement": 0.88,
                "attention_target": "explicit_target",
            },
        },
    )

    context = BodyActivityContextBuilder().build(activity)

    assert context.posture_tendency is BodyPostureTendency.OPEN
    assert context.movement_energy == 0.91
    assert context.gaze_freedom == 0.77
    assert context.engagement == 0.88
    assert context.attention_target == "explicit_target"


def test_act_projection_never_grants_execution_authority() -> None:
    projection = InteractionExpressionProjector().project(
        intention(InteractionIntentionType.ACT)
    )

    context = projection.as_context()

    assert context["content_strategy"] == "describe_only_confirmed_execution_state"
    assert context["grants_execution_authority"] is False
    assert "motion" not in context
    assert "gesture" not in context


def test_listen_and_comfort_use_receptive_body_directions() -> None:
    projector = InteractionExpressionProjector()

    listening = projector.project(intention(InteractionIntentionType.LISTEN))
    comforting = projector.project(intention(InteractionIntentionType.COMFORT))

    assert listening.posture_tendency is BodyPostureTendency.FORWARD
    assert listening.attention_intent is not None
    assert listening.attention_intent.engagement >= 0.8
    assert comforting.embodied_expression.warmth >= 0.9
    assert comforting.movement_energy < 0.25
