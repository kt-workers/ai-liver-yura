from app.runtime.agent_state import AgentState
from app.runtime.autonomous_motivation_context import (
    AutonomousMotivationContextBuilder,
)


def test_build_returns_json_compatible_motivation_context() -> None:
    context = AutonomousMotivationContextBuilder().build(AgentState())

    assert context["primary_desire"] is not None
    assert len(context["ranked_desires"]) == 3
    assert all(
        isinstance(item["desire_type"], str)
        for item in context["ranked_desires"]
    )
    assert context["moral_evaluation_available"] is False
    assert context["suppressed_activity_types"] == []
    assert context["suppression_reasons"] == ["moral_profile_not_available"]
