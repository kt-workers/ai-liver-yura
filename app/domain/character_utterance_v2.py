from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from app.domain.character_utterance import LinguisticPerformance
from app.domain.semantic_utterance_v2 import SemanticUtterancePlanV2


@dataclass(frozen=True, slots=True)
class CharacterRealizationAlignment:
    """Characterがspeech内でpropositionを実現したと申告する追跡hint。"""

    proposition_id: str
    evidence_spans: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.proposition_id, str) or not self.proposition_id.strip():
            raise ValueError("proposition_idは空にできません。")
        if not self.evidence_spans:
            raise ValueError("evidence_spansは1件以上必要です。")
        if len(self.evidence_spans) > 8:
            raise ValueError("evidence_spansは8件以下にしてください。")
        if any(
            not isinstance(span, str) or not span.strip()
            for span in self.evidence_spans
        ):
            raise ValueError("evidence_spansに空文字または非文字列は使用できません。")

    def as_context(self) -> dict[str, object]:
        return {
            "proposition_id": self.proposition_id,
            "evidence_spans": list(self.evidence_spans),
        }


@dataclass(frozen=True, slots=True)
class CharacterUtteranceV2:
    """Semantic Plan v2をCharacter Profileどおりに言語実現した構造化結果。"""

    speech: str
    linguistic_performance: LinguisticPerformance = field(
        default_factory=LinguisticPerformance
    )
    realizations: tuple[CharacterRealizationAlignment, ...] = field(
        default_factory=tuple
    )

    def __post_init__(self) -> None:
        if not isinstance(self.speech, str) or not self.speech.strip():
            raise ValueError("CharacterUtteranceV2.speechは空にできません。")
        if len(self.realizations) > 24:
            raise ValueError("realizationsは24件以下にしてください。")
        proposition_ids = [item.proposition_id for item in self.realizations]
        if len(proposition_ids) != len(set(proposition_ids)):
            raise ValueError("realizationsのproposition_idは重複できません。")
        for alignment in self.realizations:
            for span in alignment.evidence_spans:
                if span not in self.speech:
                    raise ValueError(
                        "evidence_spansはspeechに実在するsubstringである必要があります。"
                    )

    def as_context(self) -> dict[str, object]:
        return {
            "speech": self.speech,
            "linguistic_performance": self.linguistic_performance.as_context(),
            "realizations": [item.as_context() for item in self.realizations],
        }

    def validate_plan_alignment(self, plan: SemanticUtterancePlanV2) -> None:
        """意味判定をせず、Planとalignmentの構造関係だけを検証する。"""

        planned = {item.proposition_id: item for item in plan.propositions}
        realized_ids = {item.proposition_id for item in self.realizations}

        unknown = realized_ids.difference(planned)
        if unknown:
            raise ValueError(
                "Planに存在しないproposition_idがrealizationsに含まれています: "
                + ", ".join(sorted(unknown))
            )

        required = {
            item.proposition_id
            for item in plan.propositions
            if item.realization_policy == "required"
        }
        missing = required.difference(realized_ids)
        if missing:
            raise ValueError(
                "required propositionのalignmentがありません: "
                + ", ".join(sorted(missing))
            )

    @classmethod
    def from_context(cls, value: object) -> CharacterUtteranceV2 | None:
        if not isinstance(value, Mapping):
            return None
        if not {"speech", "linguistic_performance", "realizations"}.issubset(
            value.keys()
        ):
            return None

        speech = value.get("speech")
        if not isinstance(speech, str) or not speech.strip():
            return None

        performance = cls._performance_from_context(value.get("linguistic_performance"))
        if performance is None:
            return None

        raw_realizations = value.get("realizations")
        if not isinstance(raw_realizations, (list, tuple)):
            return None

        realizations: list[CharacterRealizationAlignment] = []
        for raw in raw_realizations:
            alignment = cls._alignment_from_context(raw)
            if alignment is None:
                return None
            realizations.append(alignment)

        try:
            return cls(
                speech=speech.strip(),
                linguistic_performance=performance,
                realizations=tuple(realizations),
            )
        except ValueError:
            return None

    @classmethod
    def _performance_from_context(
        cls,
        value: object,
    ) -> LinguisticPerformance | None:
        if not isinstance(value, Mapping):
            return None
        if not {"phrasing", "emphasis", "delivery_tags"}.issubset(value.keys()):
            return None

        phrasing = cls._strict_strings(value.get("phrasing"), limit=12)
        emphasis = cls._strict_strings(value.get("emphasis"), limit=12)
        delivery_tags = cls._strict_strings(value.get("delivery_tags"), limit=8)
        if phrasing is None or emphasis is None or delivery_tags is None:
            return None

        try:
            return LinguisticPerformance(
                phrasing=phrasing,
                emphasis=emphasis,
                delivery_tags=delivery_tags,
            )
        except ValueError:
            return None

    @classmethod
    def _alignment_from_context(
        cls,
        value: object,
    ) -> CharacterRealizationAlignment | None:
        if not isinstance(value, Mapping):
            return None
        if not {"proposition_id", "evidence_spans"}.issubset(value.keys()):
            return None

        proposition_id = value.get("proposition_id")
        if not isinstance(proposition_id, str) or not proposition_id.strip():
            return None
        evidence_spans = cls._strict_strings(value.get("evidence_spans"), limit=8)
        if not evidence_spans:
            return None

        try:
            return CharacterRealizationAlignment(
                proposition_id=proposition_id.strip(),
                evidence_spans=evidence_spans,
            )
        except ValueError:
            return None

    @staticmethod
    def _strict_strings(value: object, *, limit: int) -> tuple[str, ...] | None:
        if not isinstance(value, (list, tuple)):
            return None
        if len(value) > limit:
            return None

        result: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                return None
            result.append(item.strip())
        return tuple(result)
