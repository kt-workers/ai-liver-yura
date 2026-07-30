"""OBS adapters owned by Streaming Subsystem."""

from subsystems.streaming.adapters.obs.bundle import (
    ObsAdapterBundle,
    build_obs_adapter_bundle,
)
from subsystems.streaming.adapters.obs.client import (
    ObsRequestClient,
    ObsWebSocketClientConfig,
    ObsWebSocketClientFactory,
)
from subsystems.streaming.adapters.obs.contracts import (
    ObsAudioSourceState,
    ObsInspection,
    ObsPreparationPort,
    ObsPreparationSnapshot,
    ObsSourceVisibility,
    ObsStreamingControlPort,
)
from subsystems.streaming.adapters.obs.control import (
    ObsWebSocketStreamingControlAdapter,
)
from subsystems.streaming.adapters.obs.errors import (
    ObsAdapterError,
    ObsErrorMapper,
    to_streaming_error,
)
from subsystems.streaming.adapters.obs.fake_obs import (
    DisabledObsPreparationAdapter,
    DisabledObsStreamingControlAdapter,
    FakeObsPreparationAdapter,
    FakeObsPreparationConfig,
    FakeObsStreamingControlAdapter,
)
from subsystems.streaming.adapters.obs.mapper import ObsStatusMapper
from subsystems.streaming.adapters.obs.obs_websocket import (
    ObsWebSocketPreparationAdapter,
    ObsWebSocketPreparationConfig,
)

__all__ = [
    "DisabledObsPreparationAdapter",
    "DisabledObsStreamingControlAdapter",
    "FakeObsPreparationAdapter",
    "FakeObsPreparationConfig",
    "FakeObsStreamingControlAdapter",
    "ObsAdapterBundle",
    "ObsAdapterError",
    "ObsAudioSourceState",
    "ObsErrorMapper",
    "ObsInspection",
    "ObsPreparationPort",
    "ObsPreparationSnapshot",
    "ObsRequestClient",
    "ObsSourceVisibility",
    "ObsStatusMapper",
    "ObsStreamingControlPort",
    "ObsWebSocketClientConfig",
    "ObsWebSocketClientFactory",
    "ObsWebSocketPreparationAdapter",
    "ObsWebSocketPreparationConfig",
    "ObsWebSocketStreamingControlAdapter",
    "build_obs_adapter_bundle",
    "to_streaming_error",
]
