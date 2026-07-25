from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.domain.events import AgentEvent, AgentEventType


@dataclass(slots=True)
class AutonomousPlanState:
    """自律発話計画の受理・却下と再検討待機状態を保持する。"""

    default_retry_backoff_seconds: float = 2.0
    last_accepted_at: datetime | None = None
    last_rejected_at: datetime | None = None
    reconsider_after_seconds: float | None = None

    def __post_init__(self) -> None:
        self.default_retry_backoff_seconds = max(
            float(self.default_retry_backoff_seconds),
            0.0,
        )
        if self.reconsider_after_seconds is None:
            self.reconsider_after_seconds = self.default_retry_backoff_seconds
        else:
            self.reconsider_after_seconds = max(
                float(self.reconsider_after_seconds),
                0.0,
            )

    def accept(self, event: AgentEvent) -> datetime | None:
        """自律計画を受理し、計画時刻と却下待機状態を更新する。"""

        if event.event_type != AgentEventType.CURIOSITY_PEAK:
            return None

        planned_for = event.payload.get("autonomous_planned_for")
        try:
            accepted_at = (
                datetime.fromisoformat(planned_for)
                if isinstance(planned_for, str)
                else event.occurred_at
            )
        except ValueError:
            accepted_at = event.occurred_at

        self.last_accepted_at = accepted_at
        self.last_rejected_at = None
        self.reconsider_after_seconds = self.default_retry_backoff_seconds
        return accepted_at

    def reject(
        self,
        event: AgentEvent,
        *,
        rejected_at: datetime | None = None,
        reconsider_after_seconds: float | None = None,
    ) -> bool:
        """自律計画を却下し、次回の再検討可能時刻を更新する。"""

        if event.event_type != AgentEventType.CURIOSITY_PEAK:
            return False

        self.last_rejected_at = rejected_at or datetime.now(timezone.utc)
        self.reconsider_after_seconds = (
            min(300.0, max(5.0, float(reconsider_after_seconds)))
            if reconsider_after_seconds is not None
            else self.default_retry_backoff_seconds
        )
        return True

    def is_retry_backoff_active(self, now: datetime) -> bool:
        return self._is_within_pause(
            since=self.last_rejected_at,
            now=now,
            pause_seconds=self.reconsider_after_seconds or 0.0,
        )

    def is_talk_interval_active(self, now: datetime, interval_seconds: float) -> bool:
        return self._is_within_pause(
            since=self.last_accepted_at,
            now=now,
            pause_seconds=interval_seconds,
        )

    @staticmethod
    def _is_within_pause(
        *,
        since: datetime | None,
        now: datetime,
        pause_seconds: float,
    ) -> bool:
        if since is None or pause_seconds <= 0.0:
            return False
        return (now - since).total_seconds() < pause_seconds
