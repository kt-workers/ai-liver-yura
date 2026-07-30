"""Deprecated one-way compatibility boundary for OBS adapters."""

from subsystems.streaming.adapters.obs import (
    ObsAdapterError,
    ObsAudioSourceState,
    ObsErrorMapper,
    ObsInspection,
    ObsRequestClient,
    ObsSourceVisibility,
    ObsStatusMapper,
    ObsWebSocketClientConfig,
    ObsWebSocketClientFactory,
    ObsWebSocketPreparationAdapter,
    ObsWebSocketPreparationConfig,
    ObsWebSocketStreamingControlAdapter,
)

__all__ = [
    "ObsAdapterError",
    "ObsAudioSourceState",
    "ObsErrorMapper",
    "ObsInspection",
    "ObsRequestClient",
    "ObsSourceVisibility",
    "ObsStatusMapper",
    "ObsWebSocketClientConfig",
    "ObsWebSocketClientFactory",
    "ObsWebSocketPreparationAdapter",
    "ObsWebSocketPreparationConfig",
    "ObsWebSocketStreamingControlAdapter",
]
