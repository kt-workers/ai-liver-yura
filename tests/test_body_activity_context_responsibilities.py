from app.domain.activities import Activity, ActivityType
from app.domain.body import BodyPostureTendency
from app.domain.interaction_intention import (
    InteractionIntention,
    InteractionIntentionType,
)
from app.runtime.body_activity_context_policy import BodyActivityContextPolicy
from app.runtime.body_interaction_intention_resolver import (
    BodyInteractionIntentionResolver,
)
from app.runtime.interaction_expression_projector import (
    InteractionExpressionProjector,
)


def _intention(kind: InteractionIntentionType) -> InteractionIntention:
    return InteractionIntention(
        intention=kind,
        confidence=0.9,
        source="test",
        reason="responsibility_test",
        target_type="counterpart",
        target_id="user",
    )


def test_body_intention_resolver_prefers_direct_activity_context() -> None:
    direct = _intention(InteractionIntentionType.LISTEN)
    nested = _intention(InteractionIntentionType.SHARE)
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="意図探索順を確認する",
        context={
            "interaction_intention": direct.as_context(),
            "event_payload": {
                "interaction_intention": nested.as_context(),
            },
        },
    )

    resolved = BodyInteractionIntentionResolver().resolve(activity)

    assert resolved == direct


def test_body_intention_resolver_reads_safe_plan_constraint() -> None:
    expected = _intention(InteractionIntentionType.SET_BOUNDARY)
    activity = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="互換位置から意図を復元する",
        context={
            "behavior_plan": {
                "constraints": {
                    "_interaction_intention": expected.as_context(),
                }
            }
        },
    )

    resolved = BodyInteractionIntentionResolver().resolve(activity)

    assert resolved == expected


def test_body_context_policy_keeps_activity_defaults_without_intention() -> None:
    policy = BodyActivityContextPolicy()

    defaults = policy.defaults_for(ActivityType.LISTENING_MODE)
    projected = policy.apply_projection(defaults, None)

    assert projected == defaults
    assert projected.posture_tendency is BodyPostureTendency.FORWARD
    assert projected.attention_target == "conversation_partner"


def test_body_context_policy_blends_expression_without_motion_command() -> None:
    policy = BodyActivityContextPolicy()
    defaults = policy.defaults_for(ActivityType.CONVERSATION_WITH_USER)
    projection = InteractionExpressionProjector().project(
        _intention(InteractionIntentionType.SET_BOUNDARY)
    )

    projected = policy.apply_projection(defaults, projection)

    assert projected.posture_tendency is BodyPostureTendency.CLOSED
    assert projected.attention_target == "user"
    assert projected.engagement < defaults.engagement
    assert 0.0 <= projected.movement_energy <= 1.0
    assert 0.0 <= projected.gaze_freedom <= 1.0
