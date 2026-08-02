from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.domain.events import AgentEvent, AgentEventType


@dataclass(frozen=True, slots=True)
class InteractionSegmentDecision:
    """生の接触サンプルを意味のある区間刺激へ変換した結果。"""

    should_apply: bool
    weight: float | None = None
    gesture_id: str | None = None
    phase: str | None = None
    segment_index: int | None = None
    reason: str = "not_continuous_contact"


@dataclass(slots=True)
class _GestureState:
    last_applied_at: datetime
    segment_index: int


class ContinuousInteractionSegmenter:
    """高頻度のドラッグ座標を、時間区間ごとの意味刺激へ間引く。"""

    def __init__(
        self,
        *,
        interval_seconds: float = 1.0,
        start_weight: float = 0.35,
        update_weight: float = 0.35,
        end_weight: float = 0.15,
        stale_after_seconds: float = 30.0,
    ) -> None:
        self._interval_seconds = max(0.05, interval_seconds)
        self._start_weight = max(0.0, start_weight)
        self._update_weight = max(0.0, update_weight)
        self._end_weight = max(0.0, end_weight)
        self._stale_after = timedelta(seconds=max(1.0, stale_after_seconds))
        self._gestures: dict[str, _GestureState] = {}

    def decide(self, event: AgentEvent) -> InteractionSegmentDecision:
        if event.event_type != AgentEventType.USER_INTERACTION:
            return InteractionSegmentDecision(should_apply=True)

        phase = self._phase(event)
        continuous = (
            event.payload.get("continuous_contact") is True
            or phase in {"start", "update", "end"}
        )
        if not continuous:
            return InteractionSegmentDecision(should_apply=True)

        self._discard_stale(event.occurred_at)
        gesture_id = self._gesture_id(event)
        if gesture_id is None:
            return self._without_gesture_id(phase)

        if phase == "start":
            self._gestures[gesture_id] = _GestureState(
                last_applied_at=event.occurred_at,
                segment_index=0,
            )
            return InteractionSegmentDecision(
                should_apply=True,
                weight=self._start_weight,
                gesture_id=gesture_id,
                phase=phase,
                segment_index=0,
                reason="continuous_contact_started",
            )

        if phase == "end":
            state = self._gestures.pop(gesture_id, None)
            return InteractionSegmentDecision(
                should_apply=True,
                weight=self._end_weight,
                gesture_id=gesture_id,
                phase=phase,
                segment_index=(state.segment_index + 1 if state is not None else 0),
                reason="continuous_contact_ended",
            )

        state = self._gestures.get(gesture_id)
        if state is None:
            self._gestures[gesture_id] = _GestureState(
                last_applied_at=event.occurred_at,
                segment_index=0,
            )
            return InteractionSegmentDecision(
                should_apply=True,
                weight=self._update_weight,
                gesture_id=gesture_id,
                phase=phase,
                segment_index=0,
                reason="continuous_contact_resumed",
            )

        elapsed = max(
            0.0,
            (event.occurred_at - state.last_applied_at).total_seconds(),
        )
        if elapsed < self._interval_seconds:
            return InteractionSegmentDecision(
                should_apply=False,
                weight=0.0,
                gesture_id=gesture_id,
                phase=phase,
                segment_index=state.segment_index,
                reason="continuous_contact_within_segment",
            )

        state.last_applied_at = event.occurred_at
        state.segment_index += 1
        return InteractionSegmentDecision(
            should_apply=True,
            weight=self._update_weight,
            gesture_id=gesture_id,
            phase=phase,
            segment_index=state.segment_index,
            reason="continuous_contact_segment_elapsed",
        )

    def _without_gesture_id(self, phase: str | None) -> InteractionSegmentDecision:
        if phase == "start":
            weight = self._start_weight
        elif phase == "end":
            weight = self._end_weight
        elif phase == "update":
            weight = 0.0
        else:
            weight = self._update_weight
        return InteractionSegmentDecision(
            should_apply=phase != "update",
            weight=weight,
            phase=phase,
            reason="continuous_contact_without_gesture_id",
        )

    def _discard_stale(self, now: datetime) -> None:
        cutoff = now - self._stale_after
        stale_ids = [
            gesture_id
            for gesture_id, state in self._gestures.items()
            if state.last_applied_at < cutoff
        ]
        for gesture_id in stale_ids:
            self._gestures.pop(gesture_id, None)

    @staticmethod
    def _gesture_id(event: AgentEvent) -> str | None:
        value = event.payload.get("gesture_id")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    @staticmethod
    def _phase(event: AgentEvent) -> str | None:
        value = event.payload.get("contact_phase") or event.payload.get("gesture_phase")
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
        return None
