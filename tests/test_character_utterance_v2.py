from __future__ import annotations

import pytest

from app.domain.character_utterance import LinguisticPerformance
from app.domain.character_utterance_v2 import (
    CharacterRealizationAlignment,
    CharacterUtteranceV2,
)
from app.domain.semantic_utterance_v2 import (
    SemanticPropositionV2,
    SemanticUtterancePlanV2,
    SemanticValue,
)


def _proposition(
    proposition_id: str,
    *,
    policy: str = "required",
) -> SemanticPropositionV2:
    return SemanticPropositionV2(
        proposition_id=proposition_id,
        kind="internal_state",
        predicate="joy",
        value=SemanticValue(
            status="known",
            polarity="present",
            degree="high",
            certainty="medium",
        ),
        realization_policy=policy,
    )


def _plan(*propositions: SemanticPropositionV2) -> SemanticUtterancePlanV2:
    return SemanticUtterancePlanV2(
        speech_act="answer",
        propositions=tuple(propositions),
    )


def test_valid_character_utterance_round_trips_and_aligns() -> None:
    plan = _plan(_proposition("p1"))
    utterance = CharacterUtteranceV2(
        speech="まだ少し照れるけど、うれしいよ。",
        linguistic_performance=LinguisticPerformance(
            phrasing=("まだ少し照れるけど", "うれしいよ"),
            emphasis=("うれしい",),
            delivery_tags=("gentle",),
        ),
        realizations=(
            CharacterRealizationAlignment(
                proposition_id="p1",
                evidence_spans=("うれしい",),
            ),
        ),
    )

    utterance.validate_plan_alignment(plan)
    assert CharacterUtteranceV2.from_context(utterance.as_context()) == utterance


def test_duplicate_alignment_is_rejected() -> None:
    alignment = CharacterRealizationAlignment(
        proposition_id="p1",
        evidence_spans=("うれしい",),
    )
    with pytest.raises(ValueError):
        CharacterUtteranceV2(
            speech="うれしいよ。",
            realizations=(alignment, alignment),
        )


def test_evidence_not_in_speech_is_rejected() -> None:
    with pytest.raises(ValueError):
        CharacterUtteranceV2(
            speech="うれしいよ。",
            realizations=(
                CharacterRealizationAlignment(
                    proposition_id="p1",
                    evidence_spans=("悲しい",),
                ),
            ),
        )


def test_required_alignment_missing_is_rejected_against_plan() -> None:
    utterance = CharacterUtteranceV2(
        speech="短く返すね。",
        realizations=(),
    )
    with pytest.raises(ValueError, match="required proposition"):
        utterance.validate_plan_alignment(_plan(_proposition("p1")))


def test_optional_alignment_may_be_omitted() -> None:
    plan = _plan(
        _proposition("p1"),
        _proposition("p2", policy="optional"),
    )
    utterance = CharacterUtteranceV2(
        speech="うれしいよ。",
        realizations=(
            CharacterRealizationAlignment(
                proposition_id="p1",
                evidence_spans=("うれしい",),
            ),
        ),
    )

    utterance.validate_plan_alignment(plan)


def test_unknown_proposition_id_is_rejected_against_plan() -> None:
    utterance = CharacterUtteranceV2(
        speech="うれしいよ。",
        realizations=(
            CharacterRealizationAlignment(
                proposition_id="not-planned",
                evidence_spans=("うれしい",),
            ),
        ),
    )
    with pytest.raises(ValueError, match="Planに存在しない"):
        utterance.validate_plan_alignment(_plan(_proposition("p1")))


def test_context_parser_fails_closed_on_missing_evidence() -> None:
    assert (
        CharacterUtteranceV2.from_context(
            {
                "speech": "うれしいよ。",
                "linguistic_performance": {
                    "phrasing": [],
                    "emphasis": [],
                    "delivery_tags": [],
                },
                "realizations": [
                    {
                        "proposition_id": "p1",
                        "evidence_spans": [],
                    }
                ],
            }
        )
        is None
    )


def test_alignment_span_limit_is_fail_closed() -> None:
    assert (
        CharacterUtteranceV2.from_context(
            {
                "speech": "a",
                "linguistic_performance": {
                    "phrasing": [],
                    "emphasis": [],
                    "delivery_tags": [],
                },
                "realizations": [
                    {
                        "proposition_id": "p1",
                        "evidence_spans": ["a"] * 9,
                    }
                ],
            }
        )
        is None
    )
