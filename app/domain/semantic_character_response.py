from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.character_response import CharacterResponse
from app.domain.character_utterance import CharacterRealizationAlignment


@dataclass(frozen=True, slots=True)
class SemanticCharacterResponse(CharacterResponse):
    """v2 semantic pipeline内だけでalignment hintを保持するCharacterResponse。"""

    semantic_alignment: tuple[CharacterRealizationAlignment, ...] = field(
        default_factory=tuple
    )
