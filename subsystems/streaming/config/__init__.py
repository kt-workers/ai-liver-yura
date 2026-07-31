"""Streaming Subsystem-owned configuration boundaries."""

from subsystems.streaming.config.environment import (
    apply_streaming_environment_overrides,
)
from subsystems.streaming.config.loader import (
    DEFAULT_STREAMING_CONFIG_PATH,
    load_streaming_subsystem_config,
)
from subsystems.streaming.config.models import (
    StreamingSecretRefs,
    StreamingSubsystemConfig,
)
from subsystems.streaming.config.obs import (
    STREAMING_OBS_PASSWORD,
    ObsAdapterMode,
    ObsSubsystemConfig,
)
from subsystems.streaming.config.secrets import (
    CompositeSecretProvider,
    EnvironmentSecretProvider,
    NullSecretProvider,
    SecretProvider,
    StaticSecretProvider,
)
from subsystems.streaming.config.validation import (
    StreamingConfigError,
    validate_streaming_subsystem_config,
)
from subsystems.streaming.config.youtube import (
    STREAMING_YOUTUBE_CLIENT_SECRET_PATH,
    STREAMING_YOUTUBE_TOKEN_PATH,
    YouTubeAdapterMode,
    YouTubeSubsystemConfig,
)

__all__ = [
    "CompositeSecretProvider",
    "DEFAULT_STREAMING_CONFIG_PATH",
    "EnvironmentSecretProvider",
    "NullSecretProvider",
    "ObsAdapterMode",
    "ObsSubsystemConfig",
    "STREAMING_OBS_PASSWORD",
    "STREAMING_YOUTUBE_CLIENT_SECRET_PATH",
    "STREAMING_YOUTUBE_TOKEN_PATH",
    "SecretProvider",
    "StaticSecretProvider",
    "StreamingConfigError",
    "StreamingSecretRefs",
    "StreamingSubsystemConfig",
    "YouTubeAdapterMode",
    "YouTubeSubsystemConfig",
    "apply_streaming_environment_overrides",
    "load_streaming_subsystem_config",
    "validate_streaming_subsystem_config",
]
