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
from subsystems.streaming.config import (
    EnvironmentSecretProvider,
    ObsSubsystemConfig,
    SecretProvider,
    StreamingSubsystemConfig,
    YouTubeSubsystemConfig,
    validate_streaming_subsystem_config,
)


def build_streaming_subsystem(
    *,
    clock: Callable[[], datetime] | None = None,
    config: StreamingSubsystemConfig | None = None,
    secret_provider: SecretProvider | None = None,
    dependency_health_providers: Sequence[DependencyHealthProvider] = (),
    obs_config: ObsSubsystemConfig | None = None,
    youtube_config: YouTubeSubsystemConfig | None = None,
) -> StreamingSubsystemApi:
    """Build from Subsystem-owned config and externally supplied secrets."""

    if config is not None and (obs_config is not None or youtube_config is not None):
        raise ValueError("config cannot be combined with legacy adapter configs")
    subsystem_config = config or StreamingSubsystemConfig(
        youtube=youtube_config or YouTubeSubsystemConfig(),
        obs=obs_config or ObsSubsystemConfig(),
    )
    secrets = secret_provider or EnvironmentSecretProvider()
    validate_streaming_subsystem_config(subsystem_config, secrets)
    obs = build_obs_adapter_bundle(subsystem_config.obs, secrets)
    youtube = build_youtube_adapter_bundle(
        subsystem_config.youtube,
        secrets,
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
