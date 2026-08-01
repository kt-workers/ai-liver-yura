"""OBS settings boundary independent of Core configuration models."""

from dataclasses import dataclass
from enum import Enum

STREAMING_OBS_PASSWORD = "STREAMING_OBS_PASSWORD"


class ObsAdapterMode(str, Enum):
    FAKE = "fake"
    OBS_WEBSOCKET = "obs_websocket"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class ObsSubsystemConfig:
    mode: ObsAdapterMode = ObsAdapterMode.FAKE
    host: str = "127.0.0.1"
    port: int = 4455
    password_ref: str = STREAMING_OBS_PASSWORD
    connect_timeout_seconds: float = 5.0
    request_timeout_seconds: float = 5.0
    state_timeout_seconds: float = 30.0
    poll_interval_seconds: float = 0.25
    max_retries: int = 2
    retry_initial_delay_seconds: float = 0.5
    required_audio_sources: tuple[str, ...] = ()
    optional_audio_sources: tuple[str, ...] = ()
    avatar_source_name: str | None = None
    low_volume_threshold_db: float = -60.0
    max_scene_depth: int = 8
