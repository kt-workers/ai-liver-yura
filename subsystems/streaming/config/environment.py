"""Explicit environment overrides for Streaming Subsystem configuration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace

from subsystems.streaming.config.models import StreamingSubsystemConfig
from subsystems.streaming.config.obs import ObsAdapterMode
from subsystems.streaming.config.validation import StreamingConfigError
from subsystems.streaming.config.youtube import YouTubeAdapterMode


def apply_streaming_environment_overrides(
    config: StreamingSubsystemConfig,
    environ: Mapping[str, str],
) -> StreamingSubsystemConfig:
    youtube = config.youtube
    obs = config.obs

    youtube_fields: dict[str, tuple[str, Callable[[str], object]]] = {
        "STREAMING_YOUTUBE_ADAPTER": ("mode", YouTubeAdapterMode),
        "STREAMING_YOUTUBE_CLIENT_SECRET_PATH_REF": (
            "client_secret_path_ref",
            str,
        ),
        "STREAMING_YOUTUBE_TOKEN_PATH_REF": ("token_path_ref", str),
        "STREAMING_YOUTUBE_REQUEST_TIMEOUT_SECONDS": (
            "request_timeout_seconds",
            _float,
        ),
        "STREAMING_YOUTUBE_MAX_RETRIES": ("max_retries", _int),
        "STREAMING_YOUTUBE_RETRY_INITIAL_DELAY_SECONDS": (
            "retry_initial_delay_seconds",
            _float,
        ),
        "STREAMING_YOUTUBE_OAUTH_OPEN_BROWSER": ("oauth_open_browser", _bool),
        "STREAMING_YOUTUBE_OAUTH_TIMEOUT_SECONDS": (
            "oauth_timeout_seconds",
            _float,
        ),
        "STREAMING_YOUTUBE_ALLOW_LIVE_BROADCAST": (
            "allow_live_broadcast",
            _bool,
        ),
        "STREAMING_YOUTUBE_ALLOWED_PRIVACY_STATUSES": (
            "allowed_privacy_statuses",
            _csv,
        ),
    }
    obs_fields: dict[str, tuple[str, Callable[[str], object]]] = {
        "STREAMING_OBS_ADAPTER": ("mode", ObsAdapterMode),
        "STREAMING_OBS_HOST": ("host", str),
        "STREAMING_OBS_PORT": ("port", _int),
        "STREAMING_OBS_PASSWORD_REF": ("password_ref", str),
        "STREAMING_OBS_CONNECT_TIMEOUT_SECONDS": (
            "connect_timeout_seconds",
            _float,
        ),
        "STREAMING_OBS_REQUEST_TIMEOUT_SECONDS": (
            "request_timeout_seconds",
            _float,
        ),
        "STREAMING_OBS_STATE_TIMEOUT_SECONDS": ("state_timeout_seconds", _float),
        "STREAMING_OBS_POLL_INTERVAL_SECONDS": ("poll_interval_seconds", _float),
        "STREAMING_OBS_MAX_RETRIES": ("max_retries", _int),
        "STREAMING_OBS_RETRY_INITIAL_DELAY_SECONDS": (
            "retry_initial_delay_seconds",
            _float,
        ),
        "STREAMING_OBS_REQUIRED_AUDIO_SOURCES": ("required_audio_sources", _csv),
        "STREAMING_OBS_OPTIONAL_AUDIO_SOURCES": ("optional_audio_sources", _csv),
        "STREAMING_OBS_AVATAR_SOURCE_NAME": ("avatar_source_name", _optional),
        "STREAMING_OBS_LOW_VOLUME_THRESHOLD_DB": (
            "low_volume_threshold_db",
            _float,
        ),
        "STREAMING_OBS_MAX_SCENE_DEPTH": ("max_scene_depth", _int),
    }

    youtube = replace(youtube, **_values(environ, youtube_fields))
    obs = replace(obs, **_values(environ, obs_fields))
    return replace(config, youtube=youtube, obs=obs)


def _values(
    environ: Mapping[str, str],
    fields: Mapping[str, tuple[str, Callable[[str], object]]],
) -> dict[str, object]:
    values: dict[str, object] = {}
    for environment_name, (field_name, converter) in fields.items():
        raw = environ.get(environment_name)
        if raw is None:
            continue
        try:
            values[field_name] = converter(raw)
        except (TypeError, ValueError) as error:
            raise StreamingConfigError(
                environment_name,
                "invalid_environment_override",
            ) from error
    return values


def _int(value: str) -> int:
    if not value.strip():
        raise ValueError
    return int(value)


def _float(value: str) -> float:
    if not value.strip():
        raise ValueError
    return float(value)


def _bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError


def _csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _optional(value: str) -> str | None:
    return value.strip() or None
