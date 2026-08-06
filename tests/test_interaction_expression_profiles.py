from __future__ import annotations

import pytest

from app.domain.interaction_intention import (
    InteractionIntention,
    InteractionIntentionType,
)
from app.runtime.interaction_expression_profiles import (
    INTERACTION_EXPRESSION_PROFILES,
)
from app.runtime.interaction_expression_projector import (
    InteractionExpressionProjector,
)

pytestmark = pytest.mark.unit


def test_interaction_expression_profiles_cover_finite_intention_set() -> None:
    assert set(INTERACTION_EXPRESSION_PROFILES) == set(InteractionIntentionType)


def test_profile_projector_preserves_known_boundary_projection() -> None:
    projection = InteractionExpressionProjector().project(
        InteractionIntention(
            intention=InteractionIntentionType.SET_BOUNDARY,
            confidence=0.92,
            source="test",
            reason="profile_test",
            target_type="counterpart",
            target_id="user",
            observation_only=False,
        )
    )

    assert projection.embodied_expression.attitude == "guarded"
    assert projection.embodied_expression.tension == 0.58
    assert projection.attention_intent is not None
    assert projection.attention_intent.avoidance == 0.72
    assert projection.content_strategy == "state_boundary_calmly"
    assert projection.as_context()["grants_execution_authority"] is False


def test_interaction_expression_profile_contains_no_motion_or_joint_contract() -> None:
    for profile in INTERACTION_EXPRESSION_PROFILES.values():
        field_names = profile.__dataclass_fields__
        assert "motion" not in field_names
        assert "gesture" not in field_names
        assert "joint" not in field_names
        assert "angle" not in field_names
