from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class ConversationResumeState:
    """会話や外部活動の終了後に自律発話を再開する理由を保持する。"""

    explicit_end_reason: str | None = None
    observed_ongoing_activity_id: str | None = None

    def end_conversation(self, reason: str) -> None:
        normalized = reason.strip()
        if not normalized:
            raise ValueError("会話終了理由は空文字にできません。")
        self.explicit_end_reason = normalized

    def observe_ongoing_activity(self, ongoing_activity_id: str) -> None:
        normalized = ongoing_activity_id.strip()
        if not normalized:
            raise ValueError("Ongoing Activity IDは空文字にできません。")
        self.observed_ongoing_activity_id = normalized

    def clear_after_plan_accepted(self) -> None:
        self.explicit_end_reason = None
        self.observed_ongoing_activity_id = None

    def resolve_reason(
        self,
        *,
        last_user_input_at: datetime | None,
        now: datetime,
        idle_timeout_seconds: float,
    ) -> str | None:
        if self.explicit_end_reason is not None:
            return f"conversation_ended:{self.explicit_end_reason}"
        if self.observed_ongoing_activity_id is not None:
            return (
                "ongoing_activity_completed:"
                f"{self.observed_ongoing_activity_id}"
            )
        if last_user_input_at is None:
            return "no_conversation"
        elapsed_seconds = max(0.0, (now - last_user_input_at).total_seconds())
        if elapsed_seconds >= max(0.0, idle_timeout_seconds):
            return "conversation_idle_timeout"
        return None
