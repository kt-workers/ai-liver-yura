"""Build the Core-independent Streaming Subsystem object graph."""

from collections.abc import Callable, Sequence
from datetime import datetime

from subsystems.streaming.adapters import FakeStreamingRuntime
from subsystems.streaming.adapters.dependency_health import (
    CompositeDependencyHealthProvider,
)
from subsystems.streaming.adapters.obs import build_obs_adapter_bundle
from subsystems.streaming.adapters.youtube import build_youtube_adapter_bundle
from subsystems.streaming.api import StreamingSubsystemApi
from subsystems.streaming.application import (
    DependencyHealthProvider,
    DependencyHealthService,
    StreamingSubsystemService,
)
from subsystems.streaming.config import ObsSubsystemConfig, YouTubeSubsystemConfig


def build_streaming_subsystem(
    *,
    clock: Callable[[], datetime] | None = None,
    dependency_health_providers: Sequence[DependencyHealthProvider] = (),
    obs_config: ObsSubsystemConfig | None = None,
    youtube_config: YouTubeSubsystemConfig | None = None,
) -> StreamingSubsystemApi:
    """Build a fresh process shell with independent OBS and YouTube bundles."""

    obs = build_obs_adapter_bundle(obs_config or ObsSubsystemConfig())
    youtube = build_youtube_adapter_bundle(
        youtube_config or YouTubeSubsystemConfig()
    )
    health_catalog = (
        CompositeDependencyHealthProvider(dependency_health_providers)
        if clock is None
        else CompositeDependencyHealthProvider(
            dependency_health_providers,
            clock=clock,
        )
    )
    health_service = DependencyHealthService(health_catalog)
    runtime = (
        FakeStreamingRuntime(
            dependency_health=health_service,
            obs=obs,
            youtube=youtube,
        )
        if clock is None
        else FakeStreamingRuntime(
            clock=clock,
            dependency_health=health_service,
            obs=obs,
            youtube=youtube,
        )
    )
    service = StreamingSubsystemService(runtime)
    return StreamingSubsystemApi(service)
