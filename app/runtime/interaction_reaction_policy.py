from __future__ import annotations

from datetime import datetime

from app.domain.events import AgentEvent
from app.runtime.agent_state import AgentState


class InteractionReactionPolicy:
    """接触による状態変化とは独立して、声に出す頻度だけを判断する。"""

    def __init__(
        self,
        *,
        verbal_cooldown_seconds: float = 12.0,
        boundary_followup_cooldown_seconds: float = 8.0,
        boundary_repeat_seconds: float = 30.0,
    ) -> None:
        self._verbal_cooldown_seconds = verbal_cooldown_seconds
        self._boundary_followup_cooldown_seconds = (
            boundary_followup_cooldown_seconds
        )
        self._boundary_repeat_seconds = boundary_repeat_seconds
        self._last_verbal_reaction_at: datetime | None = None
        self._last_boundary_request_at: datetime | None = None

    def should_speak(self, event: AgentEvent, state: AgentState) -> bool:
        reason = next(
            (
                item.reason
                for item in reversed(state.memory.emotion_history)
                if item.source_event_id == event.event_id
            ),
            "",
        )
        previous = self._last_verbal_reaction_at
        if previous is None:
            self._last_verbal_reaction_at = event.occurred_at
            if reason == "contact_boundary_requested":
                self._last_boundary_request_at = event.occurred_at
            return True

        elapsed = max(0.0, (event.occurred_at - previous).total_seconds())
        if reason == "contact_boundary_requested":
            previous_boundary = self._last_boundary_request_at
            boundary_elapsed = (
                float("inf")
                if previous_boundary is None
                else max(
                    0.0,
                    (event.occurred_at - previous_boundary).total_seconds(),
                )
            )
            if boundary_elapsed < self._boundary_repeat_seconds:
                return False
            self._last_boundary_request_at = event.occurred_at
            self._last_verbal_reaction_at = event.occurred_at
            return True

        cooldown = (
            self._boundary_followup_cooldown_seconds
            if reason == "contact_boundary_ignored"
            else self._verbal_cooldown_seconds
        )
        if elapsed < cooldown:
            return False
        self._last_verbal_reaction_at = event.occurred_at
        return True
