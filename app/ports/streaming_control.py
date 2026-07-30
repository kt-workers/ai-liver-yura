from __future__ import annotations

from typing import Protocol

from subsystems.streaming.adapters.youtube.contracts import (
    YouTubeStreamingControlPort as YouTubeStreamingControlPort,
)


class ObsStreamingControlPort(Protocol):
    @property
    def adapter_type(self) -> str: ...

    async def start_stream(self) -> None: ...

    async def stop_stream(self) -> None: ...

    async def get_output_status(self) -> str: ...

    async def get_connection_status(self) -> str: ...

    async def disconnect(self) -> None: ...


__all__ = ["ObsStreamingControlPort", "YouTubeStreamingControlPort"]
