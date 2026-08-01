"""Core-owned immutable read models for the Streaming integration."""

from dataclasses import dataclass
from datetime import datetime

from app.integrations.streaming.connection_state import StreamingConnectionSnapshot
from app.integrations.streaming.contracts import (
    StreamingCapabilities,
    StreamingHealth,
    StreamingStatus,
)
from app.integrations.streaming.dependency_health import StreamingDependencyHealth


@dataclass(frozen=True, slots=True)
class CoreStreamingSnapshot:
    status: StreamingStatus
    health: StreamingHealth
    capabilities: StreamingCapabilities
    dependencies: tuple[StreamingDependencyHealth, ...]
    connection: StreamingConnectionSnapshot
    observed_at: datetime
