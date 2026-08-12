from __future__ import annotations

import pytest

from app.domain.character_utterance import (
    CharacterRealizationAlignment,
    CharacterUtterance,
)


def test_v2_alignment_round_trips_and_drives_compatibility_ids() -> None:
    utterance = CharacterUtterance(
        speech="たぶん、好奇心から何かしたい感じはあるよ。",
        realizations=(
            CharacterRealizationAlignment(
                proposition_id="desire-primary",
                evidence_spans=("何かしたい感じはある", "好奇心"),
            ),
        ),
    )

    assert utterance.semantic_realizations == ("desire-primary",)
    restored = CharacterUtterance.from_context(utterance.as_context())
    assert restored == utterance


def test_legacy_semantic_realizations_remain_parseable_without_alignment_spans() -> None:
    utterance = CharacterUtterance(
        speech="怒ってないよ。",
        semantic_realizations=("proposition:0:anger",),
    )

    assert utterance.realizations == (
        CharacterRealizationAlignment(
            proposition_id="proposition:0:anger",
            evidence_spans=(),
        ),
    )


def test_alignment_span_must_exist_in_speech() -> None:
    with pytest.raises(ValueError):
        CharacterUtterance(
            speech="怒ってないよ。",
            realizations=(
                CharacterRealizationAlignment(
                    proposition_id="proposition:0:anger",
                    evidence_spans=("楽しい",),
                ),
            ),
        )


def test_alignment_ids_cannot_duplicate() -> None:
    with pytest.raises(ValueError):
        CharacterUtterance(
            speech="怒ってないよ。",
            realizations=(
                CharacterRealizationAlignment("same", ("怒ってない",)),
                CharacterRealizationAlignment("same", ("怒ってない",)),
            ),
        )


def test_v2_and_legacy_ids_must_agree_when_both_are_present() -> None:
    with pytest.raises(ValueError):
        CharacterUtterance(
            speech="怒ってないよ。",
            semantic_realizations=("legacy",),
            realizations=(
                CharacterRealizationAlignment("v2", ("怒ってない",)),
            ),
        )
