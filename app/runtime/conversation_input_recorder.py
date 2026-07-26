from __future__ import annotations

from app.domain.events import AgentEvent, AgentEventType
from app.utils.conversation_log import ConversationLogger


class ConversationInputRecorder:
    """外部会話イベントを加工前の本文で会話ログへ記録する。"""

    def __init__(self, conversation_logger: ConversationLogger) -> None:
        self._conversation_logger = conversation_logger

    def record(self, event: AgentEvent) -> None:
        if event.event_type == AgentEventType.USER_TEXT:
            text = event.payload.get("text")
            source = str(event.payload.get("source") or "console")
            speaker = "console" if source == "console" else "user"
            speaker_name = None
        elif event.event_type == AgentEventType.YOUTUBE_COMMENT:
            text = event.payload.get("comment") or event.payload.get("text")
            source = "comment"
            speaker = "comment"
            speaker_name = str(
                event.payload.get("author_name")
                or event.payload.get("display_name")
                or "viewer"
            )
        else:
            return

        if not isinstance(text, str):
            return

        self._conversation_logger.record(
            speaker=speaker,
            source=source,
            text=text,
            speaker_name=speaker_name,
            occurred_at=event.occurred_at,
            event_id=event.event_id,
        )
