import pytest

from app.domain.desires import DesireState, DesireType, DesireValue
from app.domain.relationships import RelationshipState
from app.runtime.motivation_appraiser import MotivationAppraiser


def _with_effective_levels(**levels: float) -> DesireState:
    state = DesireState()
    for name, level in levels.items():
        desire_type = DesireType(name)
        current = state.get(desire_type)
        state = state.with_value(
            desire_type,
            DesireValue(
                level=level,
                baseline=current.baseline,
                sensitivity=current.sensitivity,
            ),
        )
    return state


def test_appraise_returns_stable_top_three_desires() -> None:
    state = _with_effective_levels(
        achievement=0.91,
        connection=0.82,
        expression=0.73,
        curiosity=0.64,
    )

    appraisal = MotivationAppraiser().appraise(state)

    assert [item.desire_type for item in appraisal.ranked_desires] == [
        DesireType.ACHIEVEMENT,
        DesireType.CONNECTION,
        DesireType.EXPRESSION,
    ]
    assert [item.rank for item in appraisal.ranked_desires] == [1, 2, 3]
    assert appraisal.primary_desire == DesireType.ACHIEVEMENT
    assert appraisal.expression_strength == pytest.approx(0.5)
    assert appraisal.ranked_desires[0].expressed_level == pytest.approx(0.455)


def test_relationship_increases_expression_strength() -> None:
    appraiser = MotivationAppraiser()
    state = DesireState()
    weak = RelationshipState(
        counterpart_id="weak",
        display_name="weak",
        familiarity=0.0,
        trust=0.0,
        affinity=-1.0,
    )
    strong = RelationshipState(
        counterpart_id="strong",
        display_name="strong",
        familiarity=1.0,
        trust=1.0,
        affinity=1.0,
    )

    weak_appraisal = appraiser.appraise(state, weak)
    strong_appraisal = appraiser.appraise(state, strong)

    assert weak_appraisal.expression_strength == pytest.approx(0.35)
    assert strong_appraisal.expression_strength == pytest.approx(1.0)
    assert (
        strong_appraisal.ranked_desires[0].expressed_level
        > weak_appraisal.ranked_desires[0].expressed_level
    )


def test_conflict_is_reported_only_for_defined_strong_pair() -> None:
    state = _with_effective_levels(
        connection=0.80,
        security=0.75,
        achievement=0.90,
        expression=0.20,
    )

    appraisal = MotivationAppraiser().appraise(state)

    assert len(appraisal.conflicts) == 1
    conflict = appraisal.conflicts[0]
    assert conflict.left == DesireType.CONNECTION
    assert conflict.right == DesireType.SECURITY
    assert conflict.reason == "connection_security_tension"
    assert conflict.intensity == pytest.approx(0.7125)


def test_recommendations_follow_rank_and_remove_duplicates() -> None:
    state = _with_effective_levels(
        connection=0.90,
        recognition=0.85,
        expression=0.80,
    )

    appraisal = MotivationAppraiser().appraise(state)

    assert appraisal.recommended_activity_types == (
        "conversation_with_user",
        "stream_comment_response",
        "listening_mode",
        "stream_main_segment",
        "autonomous_talk",
    )
    assert len(set(appraisal.recommended_activity_types)) == len(
        appraisal.recommended_activity_types
    )
    assert appraisal.recommended_conversation_strategies[:3] == (
        "continue_conversation",
        "acknowledge_other",
        "ask_follow_up",
    )


def test_moral_evaluation_is_explicitly_unavailable() -> None:
    appraisal = MotivationAppraiser().appraise(DesireState())

    assert appraisal.moral_evaluation_available is False
    assert appraisal.suppressed_activity_types == ()
    assert appraisal.suppression_reasons == ("moral_profile_not_available",)
