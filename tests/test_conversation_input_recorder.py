from __future__ import annotations

from datetime import datetime, timezone

from app.domain.events import AgentEvent, AgentEventType
from app.runtime.conversation_input_recorder import ConversationInputRecorder


class StubConversationLogger:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def record(self, **fields: object) -> None:
        self.records.append(fields)


def test_records_console_user_text_without_modifying_body() -> None:
    logger = StubConversationLogger()
    recorder = ConversationInputRecorder(logger)  # type: ignore[arg-type]
    occurred_at = datetime(2026, 7, 26, 8, 0, tzinfo=timezone.utc)
    event = AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"text": "  加工しない本文  ", "source": "console"},
        occurred_at=occurred_at,
    )

    recorder.record(event)

    assert logger.records == [
        {
            "speaker": "console",
            "source": "console",
            "text": "  加工しない本文  ",
            "speaker_name": None,
            "occurred_at": occurred_at,
            "event_id": event.event_id,
        }
    ]


def test_records_external_user_text_as_user() -> None:
    logger = StubConversationLogger()
    recorder = ConversationInputRecorder(logger)  # type: ignore[arg-type]
    event = AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"text": "こんにちは", "source": "browser"},
    )

    recorder.record(event)

    assert logger.records[0]["speaker"] == "user"
    assert logger.records[0]["source"] == "browser"
    assert logger.records[0]["text"] == "こんにちは"


def test_records_youtube_comment_with_author_name() -> None:
    logger = StubConversationLogger()
    recorder = ConversationInputRecorder(logger)  # type: ignore[arg-type]
    event = AgentEvent(
        event_type=AgentEventType.YOUTUBE_COMMENT,
        payload={"comment": "配信コメント", "author_name": "視聴者A"},
    )

    recorder.record(event)

    assert logger.records == [
        {
            "speaker": "comment",
            "source": "comment",
            "text": "配信コメント",
            "speaker_name": "視聴者A",
            "occurred_at": event.occurred_at,
            "event_id": event.event_id,
        }
    ]


def test_ignores_unsupported_event_and_non_string_text() -> None:
    logger = StubConversationLogger()
    recorder = ConversationInputRecorder(logger)  # type: ignore[arg-type]

    recorder.record(AgentEvent(event_type=AgentEventType.APP_STARTED))
    recorder.record(
        AgentEvent(
            event_type=AgentEventType.USER_TEXT,
            payload={"text": 123, "source": "console"},
        )
    )

    assert logger.records == []
