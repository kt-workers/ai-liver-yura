from __future__ import annotations

import pytest

from app.domain.behavior import TargetInterest


def test_target_interest_normalizes_identity_and_reason() -> None:
    interest = TargetInterest(
        target_type=" place ",
        target_id=" しまなみ海道 ",
        interest_intensity=0.9,
        knowledge_gap=0.8,
        satiation=0.2,
        reason=" 景色についてまだ分からない ",
    )

    assert interest.target_type == "place"
    assert interest.target_id == "しまなみ海道"
    assert interest.reason == "景色についてまだ分からない"
    assert interest.question_signal == 0.576


def test_target_interest_satiation_reduces_question_signal() -> None:
    unsatisfied = TargetInterest(
        target_type="topic",
        target_id="旅行",
        interest_intensity=0.9,
        knowledge_gap=0.9,
        satiation=0.1,
    )
    satisfied = TargetInterest(
        target_type="topic",
        target_id="旅行",
        interest_intensity=0.9,
        knowledge_gap=0.9,
        satiation=0.9,
    )

    assert unsatisfied.question_signal > satisfied.question_signal


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("interest_intensity", -0.1),
        ("interest_intensity", 1.1),
        ("knowledge_gap", -0.1),
        ("knowledge_gap", 1.1),
        ("satiation", -0.1),
        ("satiation", 1.1),
    ),
)
def test_target_interest_rejects_out_of_range_values(
    field: str,
    value: float,
) -> None:
    values = {
        "interest_intensity": 0.5,
        "knowledge_gap": 0.5,
        "satiation": 0.5,
    }
    values[field] = value

    with pytest.raises(ValueError):
        TargetInterest(
            target_type="topic",
            target_id="旅行",
            **values,
        )
