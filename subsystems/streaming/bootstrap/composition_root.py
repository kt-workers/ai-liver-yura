"""Build the Core-independent Streaming Subsystem object graph."""

from collections.abc import Callable
from datetime import datetime

from subsystems.streaming.adapters import FakeStreamingRuntime
from subsystems.streaming.adapters.obs import build_obs_adapter_bundle
from subsystems.streaming.adapters.youtube import build_youtube_adapter_bundle
from subsystems.streaming.api import StreamingSubsystemApi
from subsystems.streaming.application import StreamingSubsystemService
from subsystems.streaming.config import ObsSubsystemConfig, YouTubeSubsystemConfig


def build_streaming_subsystem(
    *,
    clock: Callable[[], datetime] | None = None,
    obs_config: ObsSubsystemConfig | None = None,
    youtube_config: YouTubeSubsystemConfig | None = None,
) -> StreamingSubsystemApi:
    """Build a fresh process shell with independent OBS and YouTube bundles."""

    obs = build_obs_adapter_bundle(obs_config or ObsSubsystemConfig())
    youtube = build_youtube_adapter_bundle(
        youtube_config or YouTubeSubsystemConfig()
    )
    runtime = (
        FakeStreamingRuntime(obs=obs, youtube=youtube)
        if clock is None
        else FakeStreamingRuntime(clock=clock, obs=obs, youtube=youtube)
    )
    service = StreamingSubsystemService(runtime)
    return StreamingSubsystemApi(service)
