from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.shared.contracts.activity import ActivityDefinition


@dataclass(frozen=True, slots=True)
class MotivationActivityCandidatePreference:
    """MotivationによるActivity候補の補助的な選好情報。"""

    activity_type: str
    position: int
    original_position: int
    recommendation_rank: int | None
    motivation_score: float
    pinned: bool
    reason: str

    def as_context(self) -> dict[str, object]:
        return {
            "activity_type": self.activity_type,
            "position": self.position,
            "original_position": self.original_position,
            "recommendation_rank": self.recommendation_rank,
            "motivation_score": self.motivation_score,
            "pinned": self.pinned,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class MotivationActivityCandidateRanking:
    """既存候補の順序と、その順序を説明する診断情報。"""

    definitions: tuple[ActivityDefinition, ...] = ()
    preferences: tuple[MotivationActivityCandidatePreference, ...] = ()

    def as_context(self) -> list[dict[str, object]]:
        return [preference.as_context() for preference in self.preferences]


@dataclass(frozen=True, slots=True)
class _CandidateEntry:
    definition: ActivityDefinition
    original_position: int
    pinned_position: int | None
    recommendation_rank: int | None


class MotivationActivityCandidateRanker:
    """既存Activity候補をMotivation推奨順へ安定的に並べ替える。"""

    def rank(
        self,
        definitions: Sequence[ActivityDefinition],
        motivation: Mapping[str, object] | None,
        *,
        pinned_activity_types: Sequence[str] = (),
    ) -> MotivationActivityCandidateRanking:
        known_activity_types = {
            definition.activity_type for definition in definitions
        }
        recommendations = tuple(
            activity_type
            for activity_type in self._string_sequence(
                motivation.get("recommended_activity_types")
                if motivation is not None
                else None
            )
            if activity_type in known_activity_types
        )
        recommendation_positions = {
            activity_type: index
            for index, activity_type in enumerate(recommendations, start=1)
        }
        pinned = tuple(
            activity_type
            for activity_type in self._deduplicate_strings(pinned_activity_types)
            if activity_type in known_activity_types
        )
        pinned_positions = {
            activity_type: index
            for index, activity_type in enumerate(pinned, start=1)
        }

        entries = tuple(
            _CandidateEntry(
                definition=definition,
                original_position=index,
                pinned_position=pinned_positions.get(definition.activity_type),
                recommendation_rank=recommendation_positions.get(
                    definition.activity_type
                ),
            )
            for index, definition in enumerate(definitions, start=1)
        )
        ordered = tuple(sorted(entries, key=self._sort_key))
        preferences = tuple(
            self._preference(entry, position=index)
            for index, entry in enumerate(ordered, start=1)
        )
        return MotivationActivityCandidateRanking(
            definitions=tuple(entry.definition for entry in ordered),
            preferences=preferences,
        )

    @staticmethod
    def _sort_key(entry: _CandidateEntry) -> tuple[int, int, int]:
        if entry.pinned_position is not None:
            return (0, entry.pinned_position, entry.original_position)
        if entry.recommendation_rank is not None:
            return (1, entry.recommendation_rank, entry.original_position)
        return (2, entry.original_position, entry.original_position)

    @staticmethod
    def _preference(
        entry: _CandidateEntry,
        *,
        position: int,
    ) -> MotivationActivityCandidatePreference:
        if entry.pinned_position is not None:
            score = 1.0
            reason = "ongoing_activity_preserved"
            pinned = True
        elif entry.recommendation_rank is not None:
            score = 1.0 / float(entry.recommendation_rank)
            reason = "motivation_recommendation"
            pinned = False
        else:
            score = 0.0
            reason = "original_order"
            pinned = False
        return MotivationActivityCandidatePreference(
            activity_type=entry.definition.activity_type,
            position=position,
            original_position=entry.original_position,
            recommendation_rank=entry.recommendation_rank,
            motivation_score=score,
            pinned=pinned,
            reason=reason,
        )

    @classmethod
    def _string_sequence(cls, value: object) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            return ()
        return cls._deduplicate_strings(value)

    @staticmethod
    def _deduplicate_strings(values: Sequence[object]) -> tuple[str, ...]:
        result: list[str] = []
        for value in values:
            if not isinstance(value, str):
                continue
            normalized = value.strip()
            if not normalized or normalized in result:
                continue
            result.append(normalized)
        return tuple(result)
