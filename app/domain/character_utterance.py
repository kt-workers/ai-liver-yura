from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True, slots=True)
class LinguisticPerformance:
    """Characterが選んだ言語表現上の区切り・強調。音響parameterは持たない。"""

    phrasing: tuple[str, ...] = field(default_factory=tuple)
    emphasis: tuple[str, ...] = field(default_factory=tuple)
    delivery_tags: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for values in (self.phrasing, self.emphasis, self.delivery_tags):
            if any(not item.strip() for item in values):
                raise ValueError("LinguisticPerformanceに空文字は使用できません。")
        if len(self.phrasing) > 12:
            raise ValueError("phrasingは12件以下にしてください。")
        if len(self.emphasis) > 12:
            raise ValueError("emphasisは12件以下にしてください。")
        if len(self.delivery_tags) > 8:
            raise ValueError("delivery_tagsは8件以下にしてください。")

    def as_context(self) -> dict[str, object]:
        return {
            "phrasing": list(self.phrasing),
            "emphasis": list(self.emphasis),
            "delivery_tags": list(self.delivery_tags),
        }


@dataclass(frozen=True, slots=True)
class CharacterUtterance:
    """確定済みSemantic PlanをCharacter Profileどおりに言語実現した結果。"""

    speech: str
    linguistic_performance: LinguisticPerformance = field(
        default_factory=LinguisticPerformance
    )
    semantic_realizations: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.speech.strip():
            raise ValueError("CharacterUtterance.speechは空にできません。")
        if any(not item.strip() for item in self.semantic_realizations):
            raise ValueError("semantic_realizationsに空文字は使用できません。")
        if len(self.semantic_realizations) > 24:
            raise ValueError("semantic_realizationsは24件以下にしてください。")

    def as_context(self) -> dict[str, object]:
        return {
            "speech": self.speech,
            "linguistic_performance": self.linguistic_performance.as_context(),
            "semantic_realizations": list(self.semantic_realizations),
        }

    @classmethod
    def from_context(cls, value: object) -> CharacterUtterance | None:
        if not isinstance(value, Mapping):
            return None
        speech = value.get("speech")
        if not isinstance(speech, str) or not speech.strip():
            return None

        linguistic_value = value.get("linguistic_performance")
        linguistic = dict(linguistic_value) if isinstance(linguistic_value, Mapping) else {}
        performance = LinguisticPerformance(
            phrasing=cls._strings(linguistic.get("phrasing"), limit=12),
            emphasis=cls._strings(linguistic.get("emphasis"), limit=12),
            delivery_tags=cls._strings(linguistic.get("delivery_tags"), limit=8),
        )
        realizations = cls._strings(value.get("semantic_realizations"), limit=24)
        return cls(
            speech=speech.strip(),
            linguistic_performance=performance,
            semantic_realizations=realizations,
        )

    @staticmethod
    def _strings(value: object, *, limit: int) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            return ()
        result: list[str] = []
        for item in value:
            if not isinstance(item, str):
                continue
            normalized = item.strip()
            if not normalized or normalized in result:
                continue
            result.append(normalized)
            if len(result) >= limit:
                break
        return tuple(result)
