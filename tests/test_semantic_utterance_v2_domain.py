from __future__ import annotations

from copy import deepcopy

import pytest

from app.domain.semantic_utterance import (
    SemanticProposition,
    SemanticTarget,
    SemanticUtterancePlan,
)
from app.domain.semantic_utterance_v2 import (
    LegacySemanticStateAdapter,
    SemanticPropositionV2,
    SemanticUtterancePlanV2,
    SemanticValue,
)


@pytest.mark.parametrize(
    ("state", "status", "polarity", "degree", "summary_mode"),
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
def test_legacy_state_maps_exactly_to_v2_and_round_trips(
    state: str,
    status: str,
    polarity: str | None,
    degree: str | None,
    summary_mode: str,
) -> None:
    value, actual_summary_mode = LegacySemanticStateAdapter.from_legacy(
        state=state,
        certainty="medium",
    )

    assert value.status == status
    assert value.polarity == polarity
    assert value.degree == degree
    assert value.certainty == "medium"
    assert actual_summary_mode == summary_mode
    assert (
        LegacySemanticStateAdapter.to_legacy(
            value=value,
            summary_mode=actual_summary_mode,
        )
        == state
    )


def test_legacy_adapter_rejects_unknown_state_instead_of_normalizing() -> None:
    with pytest.raises(ValueError):
        LegacySemanticStateAdapter.from_legacy(
            state="slightly_present",
            certainty="high",
        )


def test_legacy_adapter_rejects_unknown_certainty() -> None:
    with pytest.raises(ValueError):
        LegacySemanticStateAdapter.from_legacy(
            state="present",
            certainty="certain",
        )


def test_unknown_value_cannot_have_polarity_or_degree() -> None:
    with pytest.raises(ValueError):
        SemanticValue(
            status="unknown",
            polarity="present",
            degree=None,
            certainty="high",
        )


def test_degree_requires_known_present_value() -> None:
    with pytest.raises(ValueError):
        SemanticValue(
            status="known",
            polarity="absent",
            degree="low",
            certainty="high",
        )


def test_known_detail_proposition_requires_polarity() -> None:
    with pytest.raises(ValueError):
        SemanticPropositionV2(
            proposition_id="proposition:0:joy",
            kind="internal_state",
            predicate="joy",
            value=SemanticValue(
                status="known",
                polarity=None,
                degree=None,
                certainty="high",
            ),
            summary_mode="detail",
        )


def test_overview_proposition_cannot_carry_polarity_or_degree() -> None:
    with pytest.raises(ValueError):
        SemanticPropositionV2(
            proposition_id="proposition:0:current_feeling",
            kind="internal_state",
            predicate="current_feeling",
            value=SemanticValue(
                status="known",
                polarity="present",
                degree=None,
                certainty="high",
            ),
            summary_mode="overview",
        )


def _legacy_plan() -> SemanticUtterancePlan:
    return SemanticUtterancePlan(
        speech_act="answer",
        target=SemanticTarget(type="internal_state", id="current_feeling"),
        propositions=(
            SemanticProposition(
                kind="internal_state",
                predicate="current_feeling",
                state="overview",
                certainty="high",
                evidence_refs=("response_context:current_feeling",),
            ),
            SemanticProposition(
                kind="internal_state",
                predicate="joy",
                state="high",
                certainty="medium",
                concept="joy",
                evidence_refs=("emotion:joy",),
            ),
            SemanticProposition(
                kind="internal_state",
                predicate="sadness",
                state="unknown",
                certainty="low",
                evidence_refs=("emotion:sadness",),
            ),
        ),
        required_content=("現在の気分へ直接答える",),
        optional_content=("補助状態を必要な範囲で添える",),
        forbidden_additions=("未根拠の内部状態を追加しない",),
        response_length="short",
        question_budget=0,
        new_direction_budget=0,
        discourse_context={"mode": "direct_answer"},
        reasons=("direct_internal_state_question",),
    )


def test_legacy_plan_migration_assigns_stable_identity_and_policy() -> None:
    v2 = SemanticUtterancePlanV2.from_legacy(_legacy_plan())

    assert [item.proposition_id for item in v2.propositions] == [
        "proposition:0:current_feeling",
        "proposition:1:joy",
        "proposition:2:sadness",
    ]
    assert [item.realization_policy for item in v2.propositions] == [
        "required",
        "optional",
        "optional",
    ]
    assert v2.propositions[0].summary_mode == "overview"
    assert v2.propositions[1].value.degree == "high"
    assert v2.propositions[1].value.certainty == "medium"
    assert v2.propositions[2].value.status == "unknown"
    assert v2.propositions[2].value.certainty == "low"


def test_v2_context_has_no_legacy_state_and_round_trips() -> None:
    plan = SemanticUtterancePlanV2.from_legacy(_legacy_plan())

    context = plan.as_context()

    propositions = context["propositions"]
    assert isinstance(propositions, list)
    assert all("state" not in item for item in propositions)
    assert propositions[1]["value"] == {
        "status": "known",
        "polarity": "present",
        "degree": "high",
        "certainty": "medium",
    }

    restored = SemanticUtterancePlanV2.from_context(context)
    assert restored == plan
    assert restored is not None
    assert restored.as_context() == context


def test_plan_rejects_duplicate_proposition_id() -> None:
    proposition = SemanticPropositionV2(
        proposition_id="same",
        kind="internal_state",
        predicate="joy",
        value=SemanticValue(
            status="known",
            polarity="present",
            degree="low",
            certainty="high",
        ),
    )

    with pytest.raises(ValueError):
        SemanticUtterancePlanV2(
            speech_act="answer",
            propositions=(proposition, proposition),
        )


@pytest.mark.parametrize(
    "mutator",
    [
        lambda context: context.pop("speech_act"),
        lambda context: context["propositions"][0].pop("value"),
        lambda context: context["propositions"][1]["value"].update(
            {"polarity": "absent", "degree": "high"}
        ),
        lambda context: context["propositions"][1]["value"].update(
            {"polarity": 123}
        ),
        lambda context: context["propositions"][0].update(
            {"proposition_id": "proposition:1:joy"}
        ),
    ],
)
def test_v2_context_parser_fails_closed_without_semantic_repair(mutator) -> None:
    context = deepcopy(SemanticUtterancePlanV2.from_legacy(_legacy_plan()).as_context())
    mutator(context)

    assert SemanticUtterancePlanV2.from_context(context) is None
