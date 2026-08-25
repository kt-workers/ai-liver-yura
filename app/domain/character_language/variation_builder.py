from __future__ import annotations

from .contracts import CharacterLanguageConstraintView, CharacterUtterance
from .variation import (
    CharacterLanguagePriorConstraintRevision,
    CharacterLanguagePriorRealizationView,
)


def prior_realization_from_utterance(
    utterance: CharacterUtterance,
    constraints: tuple[CharacterLanguageConstraintView, ...],
) -> CharacterLanguagePriorRealizationView:
    """commit済みutteranceをbounded style-only prior viewへ投影する。"""

    if not isinstance(utterance, CharacterUtterance):
        raise ValueError("utterance は CharacterUtterance でなければなりません")
    if not isinstance(constraints, (tuple, list)):
        raise ValueError("constraints は配列でなければなりません")
    owned_constraints = tuple(constraints)
    if any(not isinstance(item, CharacterLanguageConstraintView) for item in owned_constraints):
        raise ValueError("constraints に不正な値があります")
    if len({item.constraint_id for item in owned_constraints}) != len(owned_constraints):
        raise ValueError("constraint_id は重複できません")

    candidate = utterance.candidate
    text = "".join(segment.text for segment in candidate.segments)
    return CharacterLanguagePriorRealizationView(
        utterance.utterance_id,
        candidate.semantic_plan_id,
        candidate.character_id,
        candidate.character_schema_version,
        candidate.character_definition_revision,
        tuple(
            CharacterLanguagePriorConstraintRevision(
                item.constraint_id,
                item.source_revision,
            )
            for item in owned_constraints
        ),
        text,
        utterance.committed_at,
    )


__all__ = ["prior_realization_from_utterance"]
