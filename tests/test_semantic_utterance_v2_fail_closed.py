from __future__ import annotations

from copy import deepcopy

from app.domain.semantic_utterance import (
    SemanticProposition,
    SemanticUtterancePlan,
)
from app.domain.semantic_utterance_v2 import (
    LegacySemanticStateAdapter,
    SemanticUtterancePlanV2,
)


def _overview_context() -> dict[str, object]:
    legacy = SemanticUtterancePlan(
        speech_act="answer",
        propositions=(
            SemanticProposition(
                kind="internal_state",
                predicate="current_feeling",
                state="overview",
                certainty="high",
            ),
        ),
    )
    return SemanticUtterancePlanV2.from_legacy(legacy).as_context()


def test_unknown_high_certainty_is_valid_and_round_trips() -> None:
    value, summary_mode = LegacySemanticStateAdapter.from_legacy(
        state="unknown",
        certainty="high",
    )

    assert value.status == "unknown"
    assert value.polarity is None
    assert value.degree is None
    assert value.certainty == "high"
    assert summary_mode == "detail"
    assert (
        LegacySemanticStateAdapter.to_legacy(
            value=value,
            summary_mode=summary_mode,
        )
        == "unknown"
    )


def test_non_string_nullable_polarity_is_not_silently_treated_as_null() -> None:
    context = deepcopy(_overview_context())
    propositions = context["propositions"]
    assert isinstance(propositions, list)
    propositions[0]["value"]["polarity"] = 123

    assert SemanticUtterancePlanV2.from_context(context) is None


def test_non_string_nullable_degree_is_not_silently_treated_as_null() -> None:
    context = deepcopy(_overview_context())
    propositions = context["propositions"]
    assert isinstance(propositions, list)
    propositions[0]["value"]["degree"] = {"unexpected": True}

    assert SemanticUtterancePlanV2.from_context(context) is None


def test_non_integer_budget_is_not_normalized() -> None:
    context = deepcopy(_overview_context())
    context["question_budget"] = []

    assert SemanticUtterancePlanV2.from_context(context) is None
