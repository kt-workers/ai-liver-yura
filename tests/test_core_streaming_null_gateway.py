from __future__ import annotations

import asyncio

from app.integrations.streaming import (
    NullStreamingGateway,
    StreamingOperationRequest,
    StreamingOperationType,
    StreamingStatus,
)


def test_null_gateway_is_a_no_io_unavailable_result() -> None:
    async def scenario() -> None:
        gateway = NullStreamingGateway()
        assert await gateway.get_status() is StreamingStatus.UNAVAILABLE
        assert not (await gateway.get_health()).healthy
        assert not (await gateway.get_capabilities()).values
        assert await gateway.read_events() == ()
        result = await gateway.execute(
            StreamingOperationRequest("operation-1", StreamingOperationType.START, {})
        )
        assert result.accepted is False
        assert result.error is not None
        assert result.error.code.value == "not_connected"
        await gateway.close()

    asyncio.run(scenario())
