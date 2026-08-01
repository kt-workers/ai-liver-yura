"""Core composition root for the optional Streaming Subsystem connection."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.domain.events import AgentEvent
from app.integrations.streaming.event_receiver import StreamingEventReceiver
from app.integrations.streaming.gateway import StreamingGateway
from app.integrations.streaming.http_client import (
    HttpStreamingClient,
    StreamingHttpClientConfig,
)
from app.integrations.streaming.null_gateway import NullStreamingGateway


@dataclass(frozen=True, slots=True)
class CoreStreamingIntegrationConfig:
    enabled: bool = False
    endpoint: str | None = None
    timeout_seconds: float = 5.0
    reconnect_initial_seconds: float = 0.5
    reconnect_max_seconds: float = 8.0
    token: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("streaming integration timeout must be positive")
        if self.reconnect_initial_seconds <= 0 or self.reconnect_max_seconds <= 0:
            raise ValueError("streaming reconnect intervals must be positive")
        if self.reconnect_initial_seconds > self.reconnect_max_seconds:
            raise ValueError("streaming reconnect initial interval exceeds maximum")
        if self.enabled and not self.endpoint:
            raise ValueError("streaming integration endpoint is required when enabled")

    @classmethod
    def from_environment(cls) -> CoreStreamingIntegrationConfig:
        endpoint = os.getenv("YURA_STREAMING_SUBSYSTEM_API_URL")
        enabled_value = os.getenv("YURA_STREAMING_SUBSYSTEM_ENABLED")
        enabled = (
            bool(endpoint)
            if enabled_value is None
            else enabled_value.strip().lower() not in {"0", "false", "off", "disabled"}
        )
        return cls(
            enabled=enabled,
            endpoint=endpoint,
            timeout_seconds=float(
                os.getenv("YURA_STREAMING_SUBSYSTEM_TIMEOUT_SECONDS", "5.0")
            ),
            reconnect_initial_seconds=float(
                os.getenv("YURA_STREAMING_SUBSYSTEM_RECONNECT_SECONDS", "0.5")
            ),
            reconnect_max_seconds=float(
                os.getenv("YURA_STREAMING_SUBSYSTEM_RECONNECT_MAX_SECONDS", "8.0")
            ),
            token=os.getenv("YURA_STREAMING_SUBSYSTEM_API_TOKEN"),
        )


class CoreStreamingIntegration:
    def __init__(
        self,
        gateway: StreamingGateway | NullStreamingGateway,
        receiver: StreamingEventReceiver | None,
    ) -> None:
        self.gateway = gateway
        self.receiver = receiver

    async def start(self) -> None:
        if self.receiver is not None:
            await self.receiver.start()

    async def close(self) -> None:
        if self.receiver is not None:
            await self.receiver.stop()
        else:
            await self.gateway.close()


def create_core_streaming_integration(
    publish: Callable[[AgentEvent], Awaitable[None]],
    *,
    config: CoreStreamingIntegrationConfig | None = None,
) -> CoreStreamingIntegration:
    resolved = config or CoreStreamingIntegrationConfig.from_environment()
    if not resolved.enabled or not resolved.endpoint:
        return CoreStreamingIntegration(NullStreamingGateway(), None)
    client = HttpStreamingClient(
        StreamingHttpClientConfig(
            base_url=resolved.endpoint,
            timeout_seconds=resolved.timeout_seconds,
            token=resolved.token,
        )
    )
    gateway = StreamingGateway(client, timeout_seconds=resolved.timeout_seconds)
    receiver = StreamingEventReceiver(
        gateway,
        publish,
        poll_interval_seconds=resolved.reconnect_initial_seconds,
        max_backoff_seconds=resolved.reconnect_max_seconds,
    )
    return CoreStreamingIntegration(gateway, receiver)
