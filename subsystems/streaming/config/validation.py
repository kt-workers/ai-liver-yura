"""Conditional validation for Streaming configuration and secret references."""

from __future__ import annotations

from dataclasses import dataclass

from subsystems.streaming.config.models import StreamingSubsystemConfig
from subsystems.streaming.config.obs import ObsAdapterMode, ObsSubsystemConfig
from subsystems.streaming.config.secrets import SecretProvider
from subsystems.streaming.config.youtube import (
    YouTubeAdapterMode,
    YouTubeSubsystemConfig,
)


@dataclass(frozen=True, slots=True)
class StreamingConfigError(ValueError):
    path: str
    code: str

    def __str__(self) -> str:
        return f"{self.path}: {self.code}"


def validate_streaming_subsystem_config(
    config: StreamingSubsystemConfig,
    secrets: SecretProvider,
    *,
    require_secrets: bool = True,
) -> None:
    validate_youtube_config(
        config.youtube,
        secrets,
        require_secrets=require_secrets,
    )
    validate_obs_config(config.obs, secrets, require_secrets=require_secrets)


def validate_youtube_config(
    config: YouTubeSubsystemConfig,
    secrets: SecretProvider,
    *,
    require_secrets: bool = True,
) -> None:
    _positive(config.request_timeout_seconds, "youtube.request_timeout_seconds")
    _non_negative(config.max_retries, "youtube.max_retries")
    _positive(
        config.retry_initial_delay_seconds,
        "youtube.retry_initial_delay_seconds",
    )
    _positive(config.oauth_timeout_seconds, "youtube.oauth_timeout_seconds")
    if not config.allowed_privacy_statuses or any(
        value not in {"private", "unlisted", "public"} for value in config.allowed_privacy_statuses
    ):
        raise StreamingConfigError(
            "youtube.allowed_privacy_statuses",
            "invalid_privacy_status",
        )
    if config.mode is not YouTubeAdapterMode.GOOGLE:
        return
    _required_ref(config.client_secret_path_ref, "youtube.client_secret_path_ref")
    _required_ref(config.token_path_ref, "youtube.token_path_ref")
    if not require_secrets:
        return
    if secrets.get_secret(config.client_secret_path_ref) is None:
        raise StreamingConfigError(
            "youtube.client_secret_path_ref",
            "required_secret_missing",
        )
    if secrets.get_secret(config.token_path_ref) is None:
        raise StreamingConfigError(
            "youtube.token_path_ref",
            "required_secret_missing",
        )


def validate_obs_config(
    config: ObsSubsystemConfig,
    secrets: SecretProvider,
    *,
    require_secrets: bool = True,
) -> None:
    if not config.host.strip():
        raise StreamingConfigError("obs.host", "host_missing")
    if not 1 <= config.port <= 65535:
        raise StreamingConfigError("obs.port", "port_out_of_range")
    for path, value in (
        ("obs.connect_timeout_seconds", config.connect_timeout_seconds),
        ("obs.request_timeout_seconds", config.request_timeout_seconds),
        ("obs.state_timeout_seconds", config.state_timeout_seconds),
        ("obs.retry_initial_delay_seconds", config.retry_initial_delay_seconds),
    ):
        _positive(value, path)
    if config.poll_interval_seconds < 0:
        raise StreamingConfigError("obs.poll_interval_seconds", "must_not_be_negative")
    _non_negative(config.max_retries, "obs.max_retries")
    if config.max_scene_depth < 0:
        raise StreamingConfigError("obs.max_scene_depth", "must_not_be_negative")
    if config.mode is not ObsAdapterMode.OBS_WEBSOCKET:
        return
    _required_ref(config.password_ref, "obs.password_ref")
    if not require_secrets:
        return
    if secrets.get_secret(config.password_ref) is None:
        raise StreamingConfigError("obs.password_ref", "required_secret_missing")


def _required_ref(value: str, path: str) -> None:
    if not value.strip():
        raise StreamingConfigError(path, "secret_reference_missing")


def _positive(value: float, path: str) -> None:
    if isinstance(value, bool) or value <= 0:
        raise StreamingConfigError(path, "must_be_positive")


def _non_negative(value: int, path: str) -> None:
    if isinstance(value, bool) or value < 0:
        raise StreamingConfigError(path, "must_not_be_negative")
