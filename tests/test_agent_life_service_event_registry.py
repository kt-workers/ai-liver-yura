from __future__ import annotations

from datetime import datetime, timezone

from app.domain.events import AgentEvent, AgentEventType
from app.runtime.activity_manager import ActivityManager
from app.runtime.agent_life_service import AgentLifeService
from app.runtime.processed_event_registry import ProcessedEventRegistry


class RecordingProcessedEventRegistry(ProcessedEventRegistry):
    def __init__(self) -> None:
        super().__init__()
        self.registered_event_ids: list[str] = []

    def register(self, event_id: str) -> bool:
        self.registered_event_ids.append(event_id)
        return super().register(event_id)


def test_agent_life_service_delegates_duplicate_detection_to_registry() -> None:
    registry = RecordingProcessedEventRegistry()
    service = AgentLifeService(
        ActivityManager(),
        processed_event_registry=registry,
    )
    occurred_at = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
    event = AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"text": "こんにちは"},
        occurred_at=occurred_at,
    )

    first_state = service.handle_event(event)
    duplicate_state = service.handle_event(event)

    assert registry.registered_event_ids == [event.event_id, event.event_id]
    assert first_state.last_user_input_at == occurred_at
    assert duplicate_state == first_state
