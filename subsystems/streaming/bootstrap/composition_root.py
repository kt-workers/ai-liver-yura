"""Build the Core-independent Streaming Subsystem object graph."""

from collections.abc import Callable
from datetime import datetime

from subsystems.streaming.adapters import FakeStreamingRuntime
from subsystems.streaming.adapters.youtube import build_youtube_adapter_bundle
from subsystems.streaming.api import StreamingSubsystemApi
from subsystems.streaming.application import StreamingSubsystemService
from subsystems.streaming.config import YouTubeSubsystemConfig


def build_streaming_subsystem(
    *,
    clock: Callable[[], datetime] | None = None,
    youtube_config: YouTubeSubsystemConfig | None = None,
) -> StreamingSubsystemApi:
    """Build a fresh process shell with a Subsystem-owned YouTube bundle."""

    youtube = build_youtube_adapter_bundle(
        youtube_config or YouTubeSubsystemConfig()
    )
    runtime = (
        FakeStreamingRuntime(youtube=youtube)
        if clock is None
        else FakeStreamingRuntime(clock=clock, youtube=youtube)
    )
    service = StreamingSubsystemService(runtime)
    return StreamingSubsystemApi(service)
