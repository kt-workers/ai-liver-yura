from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from app.integrations.streaming import (
    CURRENT_STREAMING_API_VERSION,
    StreamingCapabilities,
    StreamingGateway,
    StreamingHealth,
    StreamingOperationRequest,
    StreamingOperationResult,
    StreamingOperationType,
    StreamingStatus,
)
from app.integrations.streaming.errors import StreamingTransportError


class FakeClient:
    closed = False

    async def get_api_version(self):
        return CURRENT_STREAMING_API_VERSION

    async def get_status(self):
        return StreamingStatus.IDLE

    async def get_health(self):
        return StreamingHealth(
            StreamingStatus.IDLE, True, datetime.now(timezone.utc)
        )

    async def get_capabilities(self):
        return StreamingCapabilities(frozenset())

    async def list_dependency_health(self):
        return ()

    async def execute(self, request):
        return StreamingOperationResult(request.operation_id, True, StreamingStatus.READY)

    async def read_events(self, after=None):
        return ()

    async def close(self):
        self.closed = True


def test_gateway_exposes_queries_operations_and_close() -> None:
    async def scenario() -> None:
        client = FakeClient()
        gateway = StreamingGateway(client)
        assert await gateway.get_status() is StreamingStatus.IDLE
        request = StreamingOperationRequest(
            "operation-1", StreamingOperationType.PREPARE, {}
        )
        assert (await gateway.execute(request)).accepted
        await gateway.close()
        assert client.closed

    asyncio.run(scenario())


def test_gateway_maps_timeout_to_stable_transport_error() -> None:
    class SlowClient(FakeClient):
        async def get_api_version(self):
            await asyncio.sleep(0.05)
            return CURRENT_STREAMING_API_VERSION

    async def scenario() -> None:
        gateway = StreamingGateway(SlowClient(), timeout_seconds=0.001)
        with pytest.raises(StreamingTransportError) as captured:
            await gateway.get_status()
        assert captured.value.code.value == "timeout"
        assert captured.value.retryable

    asyncio.run(scenario())
