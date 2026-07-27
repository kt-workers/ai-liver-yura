from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict
from datetime import datetime, timezone

from app.domain.emotions import (
    EmotionContext,
    EmotionState,
    MoodType,
    ReactiveEmotionState,
)
from app.shared.contracts.memory import EmotionHistoryRecord


class EmotionContextBuilder:
    """内部感情と直近履歴をCharacter LLM向けの文脈へ変換する。"""

    def build(
        self,
        state: EmotionState,
        history: Iterable[EmotionHistoryRecord] = (),
        *,
        now: datetime | None = None,
        history_limit: int = 5,
    ) -> EmotionContext:
        current_time = now or datetime.now(timezone.utc)
        recent = tuple(history)[-max(1, history_limit) :]
        values = state.reactive.as_dict()
        ranked = sorted(
            (
                (name, value)
                for name, value in values.items()
                if name != "emotional_pressure" and value > 0.0
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        dominant = tuple(
            {"name": name, "intensity": intensity}
            for name, intensity in ranked[:2]
            if intensity >= 0.15
        )
        mixed = tuple(
            {"name": name, "intensity": intensity}
            for name, intensity in ranked[1:]
            if intensity >= 0.20
        )
        latest = recent[-1] if recent else None
        duration_seconds = (
            max(0.0, (current_time - latest.recorded_at).total_seconds())
            if latest is not None
            else None
        )
        pressure = state.reactive.emotional_pressure
        expression_tendency = {
            "hide_emotion": pressure < 0.55,
            "voice_leak_likelihood": self._clamp01(
                pressure * 0.7 + state.arousal * 0.3
            ),
            "overt_outburst_likelihood": self._clamp01(
                max(state.reactive.anger, state.reactive.fear) * pressure
            ),
        }
        return EmotionContext(
            current=asdict(state),
            dominant_emotions=dominant,
            mixed_emotions=mixed,
            delta=dict(latest.deltas) if latest is not None else {},
            causes=tuple(self._cause_context(item) for item in recent if item.cause_summary),
            duration_seconds=duration_seconds,
            emotional_pressure=pressure,
            expression_tendency=expression_tendency,
            recent_history=tuple(self._history_context(item) for item in recent),
        )

    def build_for_event(
        self,
        fallback_state: EmotionState,
        history: Iterable[EmotionHistoryRecord],
        *,
        source_event_id: str,
        now: datetime | None = None,
        history_limit: int = 5,
    ) -> EmotionContext:
        """対象イベント直後の状態だけを使い、後続イベントの感情混入を防ぐ。"""

        records = tuple(history)
        matching_index = next(
            (
                index
                for index in range(len(records) - 1, -1, -1)
                if records[index].source_event_id == source_event_id
            ),
            None,
        )
        if matching_index is None:
            return self.build(
                fallback_state,
                records,
                now=now,
                history_limit=history_limit,
            )
        matching = records[matching_index]
        event_state = self._state_from_mapping(matching.after) or fallback_state
        return self.build(
            event_state,
            records[: matching_index + 1],
            now=now,
            history_limit=history_limit,
        )

    @classmethod
    def _state_from_mapping(
        cls,
        value: Mapping[str, object],
    ) -> EmotionState | None:
        reactive_value = value.get("reactive")
        if not isinstance(reactive_value, Mapping):
            return None
        try:
            mood_value = value.get("mood", MoodType.NEUTRAL)
            mood = (
                mood_value
                if isinstance(mood_value, MoodType)
                else MoodType(str(mood_value))
            )
            reactive = ReactiveEmotionState(
                **{
                    name: cls._number(reactive_value.get(name))
                    for name in (
                        "joy",
                        "amusement",
                        "anger",
                        "sadness",
                        "fear",
                        "surprise",
                        "discomfort",
                        "emotional_pressure",
                    )
                }
            )
            return EmotionState(
                mood=mood,
                arousal=cls._number(value.get("arousal"), default=0.5),
                valence=cls._number(value.get("valence")),
                talkativeness=cls._number(
                    value.get("talkativeness"),
                    default=0.5,
                ),
                reactive=reactive,
            )
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _cause_context(record: EmotionHistoryRecord) -> Mapping[str, object]:
        return {
            "category": record.cause_category,
            "summary": record.cause_summary,
            "target_id": record.target_id,
            "source_event_id": record.source_event_id,
            "confidence": record.confidence,
            "relational_meaning": record.relational_meaning,
        }

    @staticmethod
    def _history_context(record: EmotionHistoryRecord) -> Mapping[str, object]:
        return {
            "source_event_id": record.source_event_id,
            "reason": record.reason,
            "deltas": dict(record.deltas),
            "cause_category": record.cause_category,
            "cause_summary": record.cause_summary,
            "target_id": record.target_id,
            "confidence": record.confidence,
            "relational_meaning": record.relational_meaning,
            "recorded_at": record.recorded_at.isoformat(),
        }

    @staticmethod
    def _clamp01(value: float) -> float:
        return max(0.0, min(1.0, value))

    @staticmethod
    def _number(value: object, *, default: float = 0.0) -> float:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        return default
