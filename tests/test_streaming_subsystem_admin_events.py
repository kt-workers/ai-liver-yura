import pytest

from app.integrations.streaming import (
    StreamingOperationRequest,
    StreamingOperationType,
)
from subsystems.streaming.admin_api.service import StreamingAdminService
from subsystems.streaming.bootstrap import build_streaming_subsystem


@pytest.mark.asyncio
async def test_events_support_replay_after_event_id() -> None:
    subsystem = build_streaming_subsystem()
    service = StreamingAdminService(subsystem)
    await subsystem.execute_operation(
        StreamingOperationRequest("prepare-1", StreamingOperationType.PREPARE, {})
    )
    events = await service.events_after(None)
    assert events
    assert events[0].event_id
    assert await service.events_after(events[-1].event_id) == ()


@pytest.mark.asyncio
async def test_event_buffer_is_bounded() -> None:
    service = StreamingAdminService(build_streaming_subsystem())
    for index in range(300):
        service._emit("test.changed", str(index))
    assert len(await service.events_after(None)) == 256
