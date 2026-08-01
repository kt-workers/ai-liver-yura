from __future__ import annotations

import asyncio

from app.integrations.streaming import (
    CoreStreamingIntegrationConfig,
    NullStreamingGateway,
    create_core_streaming_integration,
)


def test_disabled_composition_uses_null_gateway_without_io() -> None:
    async def publish(_event):
        raise AssertionError("disabled integration must not publish")

    integration = create_core_streaming_integration(
        publish,
        config=CoreStreamingIntegrationConfig(enabled=False),
    )
    assert isinstance(integration.gateway, NullStreamingGateway)
    asyncio.run(integration.start())
    asyncio.run(integration.close())


def test_token_is_not_exposed_in_configuration_repr() -> None:
    config = CoreStreamingIntegrationConfig(
        enabled=True,
        endpoint="http://127.0.0.1:8781",
        token="super-secret-value",
    )
    assert "super-secret-value" not in repr(config)
