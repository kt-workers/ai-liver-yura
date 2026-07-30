from __future__ import annotations

from dataclasses import dataclass, field

from app.adapters.obs.obs_error_mapper import ObsAdapterError
from subsystems.streaming.adapters.youtube.fake_youtube import (
    FakeYouTubeStreamingControlAdapter as FakeYouTubeStreamingControlAdapter,
)


@dataclass(slots=True)
class FakeObsStreamingControlAdapter:
    statuses: list[str] = field(default_factory=lambda: ["idle", "active", "active"])
    adapter_type: str = "fake"
    start_calls: int = 0
    stop_calls: int = 0

    async def start_stream(self) -> None:
        self.start_calls += 1

    async def get_output_status(self) -> str:
        return self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]

    async def stop_stream(self) -> None:
        self.stop_calls += 1

    async def get_connection_status(self) -> str:
        return "connected"

    async def disconnect(self) -> None:
        return None


@dataclass(slots=True)
class DisabledObsStreamingControlAdapter:
    adapter_type: str = "disabled"

    async def start_stream(self) -> None:
        raise ObsAdapterError("configuration", "obs.disabled")

    async def stop_stream(self) -> None:
        return None

    async def get_output_status(self) -> str:
        return "unknown"

    async def get_connection_status(self) -> str:
        return "disabled"

    async def disconnect(self) -> None:
        return None
