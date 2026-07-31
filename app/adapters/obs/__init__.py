"""Deprecated compatibility import.

Canonical implementation: ``subsystems.streaming.adapters.obs``.
Removal target: phase K.
"""

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
