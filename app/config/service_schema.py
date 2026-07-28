from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypeAlias


@dataclass(frozen=True, slots=True)
class OpenAiServiceSettings:
    base_url: str
    api_key_env: str
    timeout_seconds: float
    type: Literal["openai"] = field(default="openai", init=False)


@dataclass(frozen=True, slots=True)
class OllamaServiceSettings:
    base_url: str
    timeout_seconds: float
    type: Literal["ollama"] = field(default="ollama", init=False)


@dataclass(frozen=True, slots=True)
class VoiceVoxServiceSettings:
    base_url: str
    timeout_seconds: float
    type: Literal["voicevox"] = field(default="voicevox", init=False)


@dataclass(frozen=True, slots=True)
class PostgresServiceSettings:
    dsn_env: str
    type: Literal["postgres"] = field(default="postgres", init=False)


@dataclass(frozen=True, slots=True)
class YouTubeServiceSettings:
    type: Literal["youtube", "youtube_api", "google", "google_youtube"]
    client_secret_path_env: str
    token_path_env: str
    request_timeout_seconds: float
    max_retries: int
    retry_initial_delay_seconds: float
    oauth_open_browser: bool
    allow_live_broadcast: bool
    oauth_timeout_seconds: float
    allowed_privacy_statuses: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FakeYouTubeServiceSettings:
    client_secret_path_env: str
    token_path_env: str
    request_timeout_seconds: float
    max_retries: int
    retry_initial_delay_seconds: float
    oauth_open_browser: bool
    allow_live_broadcast: bool
    oauth_timeout_seconds: float
    allowed_privacy_statuses: tuple[str, ...]
    type: Literal["fake"] = field(default="fake", init=False)


@dataclass(frozen=True, slots=True)
class ObsWebSocketServiceSettings:
    host: str
    port: int
    password_env: str | None
    connect_timeout_seconds: float
    request_timeout_seconds: float
    max_retries: int
    retry_initial_delay_seconds: float
    websocket_url: str | None = None
    type: Literal["obs_websocket"] = field(default="obs_websocket", init=False)


@dataclass(frozen=True, slots=True)
class FakeObsServiceSettings:
    type: Literal["fake"] = field(default="fake", init=False)


@dataclass(frozen=True, slots=True)
class DisabledServiceSettings:
    type: Literal["disabled"] = field(default="disabled", init=False)


ServiceSettings: TypeAlias = (
    OpenAiServiceSettings
    | OllamaServiceSettings
    | VoiceVoxServiceSettings
    | PostgresServiceSettings
    | YouTubeServiceSettings
    | FakeYouTubeServiceSettings
    | ObsWebSocketServiceSettings
    | FakeObsServiceSettings
    | DisabledServiceSettings
)

HttpAiServiceSettings: TypeAlias = (
    OpenAiServiceSettings | OllamaServiceSettings | VoiceVoxServiceSettings
)
