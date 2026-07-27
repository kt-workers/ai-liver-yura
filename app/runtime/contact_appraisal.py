from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta

from app.domain.emotions import EmotionState, RelationalMeaning
from app.domain.events import AgentEvent
from app.domain.relationships import RelationshipState
from app.shared.contracts.memory import EmotionHistoryRecord


@dataclass(frozen=True, slots=True)
class ContactAppraisal:
    """接触を非言語コミュニケーションとして評価した結果。"""

    meaning: str
    pleasantness: float
    safety: float
    overstimulation: float
    boundary_violation_count: int = 0


class ContactAppraiser:
    """関係性、現在状態、触れ方、境界履歴から接触の意味を評価する。"""

    _BOUNDARY_REASONS = {
        "contact_boundary_requested",
        "contact_boundary_ignored",
        "contact_boundary_guarded",
    }

    def appraise(
        self,
        event: AgentEvent,
        *,
        current: EmotionState,
        relationship: RelationshipState | None,
        recent_history: Sequence[EmotionHistoryRecord],
    ) -> ContactAppraisal:
        kind = str(event.payload.get("stimulus_kind") or "tap")
        region = str(event.payload.get("contact_region") or "center")
        burst_count = self._burst_count(event.payload.get("interaction_burst_count"))
        duration_ms = self._number(
            event.payload.get("contact_duration_ms")
            if event.payload.get("continuous_contact")
            else event.payload.get("duration_ms")
        )

        trust = relationship.trust if relationship is not None else 0.5
        affinity = relationship.affinity if relationship is not None else 0.0
        familiarity = relationship.familiarity if relationship is not None else 0.0
        relationship_warmth = 0.40 * (trust - 0.5) + 0.22 * affinity + 0.18 * familiarity

        pleasantness = {
            "tap": 0.08,
            "double_tap": 0.10,
            "long_press": 0.15,
            "drag": 0.06,
        }.get(kind, 0.06)
        pleasantness += {
            "center": 0.08,
            "upper": 0.06,
            "lower": -0.06,
            "periphery": 0.0,
        }.get(region, 0.0)
        pleasantness += relationship_warmth
        pleasantness += max(-0.08, min(0.08, current.valence * 0.12))
        residual_tension = self._clamp(
            current.reactive.discomfort * 0.45
            + current.reactive.anger * 0.35
            + current.reactive.emotional_pressure * 0.20
        )
        pleasantness -= residual_tension * 0.25

        repeated = max(0, burst_count - 2)
        repetition_load = min(0.35, repeated * repeated * 0.018)
        duration_load = (
            min(0.18, max(0.0, duration_ms - 900.0) / 5000.0)
            if kind in {"long_press", "drag"}
            else 0.0
        )
        arousal_load = max(0.0, current.arousal - 0.72) * 0.35
        overstimulation = min(
            1.0,
            repetition_load + duration_load + arousal_load,
        )
        pleasantness -= overstimulation * (0.55 - relationship_warmth * 0.20)

        safety = (
            0.62
            + 0.32 * (trust - 0.5)
            + 0.18 * affinity
            + 0.10 * familiarity
            - overstimulation * 0.35
            - (0.08 if region == "lower" else 0.0)
        )
        safety = self._clamp(safety)
        pleasantness = max(-1.0, min(1.0, pleasantness))

        boundary_history = self._recent_boundary_history(event, recent_history)
        violation_count = sum(
            1 for item in boundary_history if item.reason == "contact_boundary_ignored"
        )
        if boundary_history:
            elapsed = max(
                0.0,
                (event.occurred_at - boundary_history[-1].recorded_at).total_seconds(),
            )
            if elapsed > 12.0:
                return ContactAppraisal(
                    meaning="boundary_guarded",
                    pleasantness=min(pleasantness, -0.08),
                    safety=min(safety, 0.45),
                    overstimulation=max(overstimulation, 0.25),
                    boundary_violation_count=violation_count,
                )
            return ContactAppraisal(
                meaning="boundary_ignored",
                pleasantness=min(pleasantness, -0.35),
                safety=min(safety, 0.25),
                overstimulation=max(overstimulation, 0.55),
                boundary_violation_count=violation_count + 1,
            )

        if residual_tension >= 0.36:
            meaning = "guarded"
        elif overstimulation >= 0.58 or (
            current.reactive.discomfort >= 0.45 and pleasantness < 0.05
        ):
            meaning = "boundary_requested"
        elif overstimulation >= 0.28 or pleasantness <= -0.16:
            meaning = "overstimulating"
        elif pleasantness >= 0.22 and current.arousal <= 0.72:
            meaning = "comforting"
        elif pleasantness >= 0.10:
            meaning = "affectionate"
        elif pleasantness >= 0.02:
            meaning = "playful"
        else:
            meaning = "ambiguous"

        return ContactAppraisal(
            meaning=meaning,
            pleasantness=pleasantness,
            safety=safety,
            overstimulation=overstimulation,
        )

    def _recent_boundary_history(
        self,
        event: AgentEvent,
        history: Sequence[EmotionHistoryRecord],
    ) -> tuple[EmotionHistoryRecord, ...]:
        cutoff = event.occurred_at - timedelta(seconds=120)
        repair_at = max(
            (
                item.recorded_at
                for item in history
                if item.relational_meaning == RelationalMeaning.REPAIR_ATTEMPT.value
            ),
            default=None,
        )
        return tuple(
            item
            for item in history
            if (
                item.recorded_at >= cutoff
                and item.reason in self._BOUNDARY_REASONS
                and (repair_at is None or item.recorded_at > repair_at)
            )
        )

    @staticmethod
    def _burst_count(value: object) -> int:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return max(1, min(10, int(value)))
        return 1

    @staticmethod
    def _number(value: object) -> float:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        return 0.0

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(1.0, value))
