from __future__ import annotations

import pytest

from app.domain.semantic_utterance import (
    SemanticProposition,
    SemanticUtterancePlan,
    SemanticValue,
)


@pytest.mark.parametrize(
    ("legacy_state", "status", "polarity", "degree", "summary_mode"),
    [
        ("absent", "known", "absent", None, "detail"),
        ("present", "known", "present", None, "detail"),
        ("low", "known", "present", "low", "detail"),
        ("moderate", "known", "present", "moderate", "detail"),
        ("high", "known", "present", "high", "detail"),
        ("very_high", "known", "present", "very_high", "detail"),
        ("unknown", "unknown", None, None, "detail"),
        ("overview", "known", None, None, "overview"),
    ],
)
def test_legacy_state_normalizes_to_orthogonal_value(
    legacy_state: str,
    status: str,
    polarity: str | None,
    degree: str | None,
    summary_mode: str,
) -> None:
    proposition = SemanticProposition(
        kind="self_state",
        predicate="target",
        state=legacy_state,
        certainty="medium",
    )

    assert proposition.value is not None
    assert proposition.value.status == status
    assert proposition.value.polarity == polarity
    assert proposition.value.degree == degree
    assert proposition.value.certainty == "medium"
    assert proposition.summary_mode == summary_mode
    assert proposition.state == legacy_state


def test_v2_value_can_round_trip_through_context_without_using_legacy_state_as_authority() -> None:
    original = SemanticUtterancePlan(
        speech_act="direct_answer",
        propositions=(
            SemanticProposition(
                kind="self_state",
                predicate="current_desire",
                state="present",
                certainty="medium",
                concept="curiosity",
                value=SemanticValue(
                    status="known",
                    polarity="present",
                    degree=None,
                    certainty="medium",
                ),
                proposition_id="desire-primary",
                realization_policy="required",
            ),
        ),
    )

    restored = SemanticUtterancePlan.from_context(original.as_context())

    assert restored is not None
    proposition = restored.propositions[0]
    assert proposition.proposition_id == "desire-primary"
    assert proposition.realization_policy == "required"
    assert proposition.value is not None
    assert proposition.value.as_context() == {
        "status": "known",
        "polarity": "present",
        "degree": None,
        "certainty": "medium",
    }
    assert proposition.state == "present"


def test_plan_assigns_compatibility_ids_and_realization_policy_once() -> None:
    plan = SemanticUtterancePlan(
        speech_act="direct_answer",
        propositions=(
            SemanticProposition(kind="self_state", predicate="current_feeling", state="overview"),
            SemanticProposition(kind="self_state_dimension", predicate="calm", state="moderate"),
        ),
    )

    assert plan.propositions[0].proposition_id == "proposition:0:current_feeling"
    assert plan.propositions[0].realization_policy == "required"
    assert plan.propositions[1].proposition_id == "proposition:1:calm"
    assert plan.propositions[1].realization_policy == "optional"


@pytest.mark.parametrize(
    "value",
    [
        SemanticValue(status="unknown", certainty="high"),
        SemanticValue(status="known", polarity="absent", certainty="high"),
        SemanticValue(
            status="known",
            polarity="present",
            degree="low",
            certainty="high",
        ),
    ],
)
def test_valid_semantic_values_have_unique_legacy_projection(value: SemanticValue) -> None:
    state = value.legacy_state()
    restored = SemanticValue.from_legacy_state(state, certainty=value.certainty)
    assert restored == value


def test_unknown_rejects_polarity_or_degree() -> None:
    with pytest.raises(ValueError):
        SemanticValue(status="unknown", polarity="present", certainty="low")


def test_absent_rejects_degree() -> None:
    with pytest.raises(ValueError):
        SemanticValue(
            status="known",
            polarity="absent",
            degree="low",
            certainty="high",
        )


def test_degree_requires_present_polarity() -> None:
    with pytest.raises(ValueError):
        SemanticValue(status="known", degree="high", certainty="high")


def test_detail_known_requires_polarity() -> None:
    with pytest.raises(ValueError):
        SemanticProposition(
            kind="self_state",
            predicate="current_feeling",
            value=SemanticValue(status="known", certainty="high"),
            certainty="high",
            summary_mode="detail",
        )


def test_overview_requires_known_value_without_polarity_or_degree() -> None:
    proposition = SemanticProposition(
        kind="self_state",
        predicate="current_feeling",
        value=SemanticValue(status="known", certainty="high"),
        certainty="high",
        summary_mode="overview",
    )
    assert proposition.state == "overview"


def test_duplicate_proposition_ids_fail_closed() -> None:
    with pytest.raises(ValueError):
        SemanticUtterancePlan(
            speech_act="direct_answer",
            propositions=(
                SemanticProposition(
                    kind="self_state",
                    predicate="joy",
                    state="high",
                    proposition_id="same",
                ),
                SemanticProposition(
                    kind="self_state_dimension",
                    predicate="calm",
                    state="moderate",
                    proposition_id="same",
                ),
            ),
        )
