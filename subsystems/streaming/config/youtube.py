"""YouTube settings boundary independent of Core configuration models."""

from dataclasses import dataclass
from enum import Enum

STREAMING_YOUTUBE_CLIENT_SECRET_PATH = "STREAMING_YOUTUBE_CLIENT_SECRET_PATH"
STREAMING_YOUTUBE_TOKEN_PATH = "STREAMING_YOUTUBE_TOKEN_PATH"


class YouTubeAdapterMode(str, Enum):
    FAKE = "fake"
    GOOGLE = "google"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class YouTubeSubsystemConfig:
    mode: YouTubeAdapterMode = YouTubeAdapterMode.FAKE
    client_secret_path_ref: str = STREAMING_YOUTUBE_CLIENT_SECRET_PATH
    token_path_ref: str = STREAMING_YOUTUBE_TOKEN_PATH
    request_timeout_seconds: float = 15.0
    max_retries: int = 2
    retry_initial_delay_seconds: float = 1.0
    oauth_open_browser: bool = True
    oauth_timeout_seconds: float = 300.0
    allow_live_broadcast: bool = False
    allowed_privacy_statuses: tuple[str, ...] = ("private", "unlisted", "public")
