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
class CharacterRealizationAlignment:
    """Characterがどのspeech spanでpropositionを表現したかを示す非authority metadata。"""

    proposition_id: str
    evidence_spans: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        proposition_id = self.proposition_id.strip()
        if not proposition_id:
            raise ValueError("CharacterRealizationAlignment.proposition_idは空にできません。")
        if len(self.evidence_spans) > 12:
            raise ValueError("alignment evidence_spansは12件以下にしてください。")
        normalized_spans: list[str] = []
        for span in self.evidence_spans:
            normalized = span.strip()
            if not normalized:
                raise ValueError("alignment evidence_spansに空文字は使用できません。")
            if normalized not in normalized_spans:
                normalized_spans.append(normalized)
        object.__setattr__(self, "proposition_id", proposition_id)
        object.__setattr__(self, "evidence_spans", tuple(normalized_spans))

    def as_context(self) -> dict[str, object]:
        return {
            "proposition_id": self.proposition_id,
            "evidence_spans": list(self.evidence_spans),
        }

    @classmethod
    def from_context(cls, value: object) -> "CharacterRealizationAlignment" | None:
        if not isinstance(value, Mapping):
            return None
        proposition_id = value.get("proposition_id")
        if not isinstance(proposition_id, str) or not proposition_id.strip():
            return None
        spans = CharacterUtterance._strings(value.get("evidence_spans"), limit=12)
        try:
            return cls(proposition_id=proposition_id, evidence_spans=spans)
        except ValueError:
            return None


@dataclass(frozen=True, slots=True)
class CharacterUtterance:
    """確定済みSemantic PlanをCharacter Profileどおりに言語実現した結果。

    ``semantic_realizations`` は旧互換ID列。v2では ``realizations`` のalignmentを使用する。
    alignmentは意味authorityではなく、独立Verifierへのspan hintである。
    """

    speech: str
    linguistic_performance: LinguisticPerformance = field(
        default_factory=LinguisticPerformance
    )
    semantic_realizations: tuple[str, ...] = field(default_factory=tuple)
    realizations: tuple[CharacterRealizationAlignment, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        speech = self.speech.strip()
        if not speech:
            raise ValueError("CharacterUtterance.speechは空にできません。")
        legacy_ids = self._normalized_ids(self.semantic_realizations)
        if len(legacy_ids) > 24:
            raise ValueError("semantic_realizationsは24件以下にしてください。")
        if len(self.realizations) > 24:
            raise ValueError("realizationsは24件以下にしてください。")

        alignments = tuple(self.realizations)
        alignment_ids = tuple(item.proposition_id for item in alignments)
        if len(set(alignment_ids)) != len(alignment_ids):
            raise ValueError("realizations.proposition_idが重複しています。")

        if alignments and legacy_ids and alignment_ids != legacy_ids:
            raise ValueError("realizationsとsemantic_realizationsのIDが一致しません。")
        if alignments and not legacy_ids:
            legacy_ids = alignment_ids
        if legacy_ids and not alignments:
            # Legacy候補はspanを自己申告していない。v2 verifierではhintなしとして扱う。
            alignments = tuple(
                CharacterRealizationAlignment(proposition_id=item, evidence_spans=())
                for item in legacy_ids
            )

        for alignment in alignments:
            for span in alignment.evidence_spans:
                if span not in speech:
                    raise ValueError("alignment evidence spanがspeechに存在しません。")

        object.__setattr__(self, "speech", speech)
        object.__setattr__(self, "semantic_realizations", legacy_ids)
        object.__setattr__(self, "realizations", alignments)

    def as_context(self) -> dict[str, object]:
        return {
            "speech": self.speech,
            "linguistic_performance": self.linguistic_performance.as_context(),
            "realizations": [item.as_context() for item in self.realizations],
            # 移行互換。新規Structured Outputではrealizationsを使用する。
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

        alignments: list[CharacterRealizationAlignment] = []
        raw_alignments = value.get("realizations")
        if isinstance(raw_alignments, (list, tuple)):
            for raw_alignment in raw_alignments:
                alignment = CharacterRealizationAlignment.from_context(raw_alignment)
                if alignment is None:
                    return None
                alignments.append(alignment)

        legacy_ids = cls._strings(value.get("semantic_realizations"), limit=24)
        try:
            return cls(
                speech=speech,
                linguistic_performance=performance,
                semantic_realizations=legacy_ids,
                realizations=tuple(alignments),
            )
        except ValueError:
            return None

    @staticmethod
    def _normalized_ids(values: tuple[str, ...]) -> tuple[str, ...]:
        result: list[str] = []
        for item in values:
            normalized = item.strip()
            if not normalized:
                raise ValueError("semantic_realizationsに空文字は使用できません。")
            if normalized not in result:
                result.append(normalized)
        return tuple(result)

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
