import pytest

from app.domain.desires import DesireType
from app.domain.motivation import DesireConflict, MotivationAppraisal, RankedDesire


def test_ranked_desire_clamps_levels_and_validates_rank() -> None:
    desire = RankedDesire(
        desire_type=DesireType.CONNECTION,
        rank=1,
        effective_level=1.2,
        expressed_level=-0.2,
    )

    assert desire.effective_level == 1.0
    assert desire.expressed_level == 0.0

    with pytest.raises(ValueError, match="rankは1以上"):
        RankedDesire(
            desire_type=DesireType.CONNECTION,
            rank=0,
            effective_level=0.5,
            expressed_level=0.5,
        )


def test_desire_conflict_requires_different_desires_and_reason() -> None:
    with pytest.raises(ValueError, match="同じ欲望"):
        DesireConflict(
            left=DesireType.SECURITY,
            right=DesireType.SECURITY,
            intensity=0.5,
            reason="same",
        )

    with pytest.raises(ValueError, match="reasonは空"):
        DesireConflict(
            left=DesireType.CONNECTION,
            right=DesireType.SECURITY,
            intensity=0.5,
            reason="",
        )


def test_motivation_appraisal_exposes_primary_and_safe_context() -> None:
    appraisal = MotivationAppraisal(
        ranked_desires=(
            RankedDesire(
                desire_type=DesireType.CURIOSITY,
                rank=1,
                effective_level=0.8,
                expressed_level=0.4,
            ),
        ),
        expression_strength=0.5,
        recommended_activity_types=("topic_exploration",),
        recommended_conversation_strategies=("ask_for_detail",),
    )

    context = appraisal.as_context()

    assert appraisal.primary_desire == DesireType.CURIOSITY
    assert context["primary_desire"] == "curiosity"
    assert context["ranked_desires"][0]["effective_level"] == pytest.approx(0.8)
    assert context["moral_evaluation_available"] is False
    assert context["suppressed_activity_types"] == []
    assert context["suppression_reasons"] == ["moral_profile_not_available"]


def test_unavailable_moral_evaluation_cannot_suppress_activity() -> None:
    with pytest.raises(ValueError, match="Moral評価が利用不可"):
        MotivationAppraisal(
            moral_evaluation_available=False,
            suppressed_activity_types=("autonomous_talk",),
        )
