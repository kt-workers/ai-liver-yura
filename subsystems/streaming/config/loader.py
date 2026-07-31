"""Strict YAML loader for the Streaming Subsystem-owned configuration."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from subsystems.streaming.config.environment import (
    apply_streaming_environment_overrides,
)
from subsystems.streaming.config.models import StreamingSubsystemConfig
from subsystems.streaming.config.obs import ObsAdapterMode, ObsSubsystemConfig
from subsystems.streaming.config.secrets import NullSecretProvider, SecretProvider
from subsystems.streaming.config.validation import (
    StreamingConfigError,
    validate_streaming_subsystem_config,
)
from subsystems.streaming.config.youtube import (
    YouTubeAdapterMode,
    YouTubeSubsystemConfig,
)

DEFAULT_STREAMING_CONFIG_PATH = (
    Path(__file__).parents[3] / "config" / "subsystems" / "streaming.yaml"
)


def load_streaming_subsystem_config(
    path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    secret_provider: SecretProvider | None = None,
) -> StreamingSubsystemConfig:
    source_path = Path(path or DEFAULT_STREAMING_CONFIG_PATH).expanduser().resolve()
    try:
        loaded = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise StreamingConfigError("config", "file_unavailable") from error
    if not isinstance(loaded, Mapping):
        raise StreamingConfigError("config", "root_must_be_mapping")
    root = _mapping(loaded, "config")
    _reject_unknown(root, {"streaming"}, "config")
    streaming = _mapping(root.get("streaming"), "streaming")
    _reject_unknown(streaming, {"youtube", "obs"}, "streaming")

    config = StreamingSubsystemConfig(
        youtube=_load_youtube(
            _mapping(streaming.get("youtube", {}), "streaming.youtube")
        ),
        obs=_load_obs(_mapping(streaming.get("obs", {}), "streaming.obs")),
        source_path=source_path,
    )
    config = apply_streaming_environment_overrides(
        config,
        os.environ if environ is None else environ,
    )
    provider = secret_provider or NullSecretProvider()
    validate_streaming_subsystem_config(
        config,
        provider,
        require_secrets=secret_provider is not None,
    )
    return config


def _load_youtube(value: dict[str, Any]) -> YouTubeSubsystemConfig:
    path = "streaming.youtube"
    allowed = {
        "adapter",
        "client_secret_path_ref",
        "token_path_ref",
        "request_timeout_seconds",
        "max_retries",
        "retry_initial_delay_seconds",
        "oauth_open_browser",
        "oauth_timeout_seconds",
        "allow_live_broadcast",
        "allowed_privacy_statuses",
    }
    _reject_unknown(value, allowed, path)
    defaults = YouTubeSubsystemConfig()
    return YouTubeSubsystemConfig(
        mode=_enum(value, "adapter", YouTubeAdapterMode, defaults.mode, path),
        client_secret_path_ref=_string(
            value,
            "client_secret_path_ref",
            defaults.client_secret_path_ref,
            path,
        ),
        token_path_ref=_string(
            value,
            "token_path_ref",
            defaults.token_path_ref,
            path,
        ),
        request_timeout_seconds=_number(
            value,
            "request_timeout_seconds",
            defaults.request_timeout_seconds,
            path,
        ),
        max_retries=_integer(value, "max_retries", defaults.max_retries, path),
        retry_initial_delay_seconds=_number(
            value,
            "retry_initial_delay_seconds",
            defaults.retry_initial_delay_seconds,
            path,
        ),
        oauth_open_browser=_boolean(
            value,
            "oauth_open_browser",
            defaults.oauth_open_browser,
            path,
        ),
        oauth_timeout_seconds=_number(
            value,
            "oauth_timeout_seconds",
            defaults.oauth_timeout_seconds,
            path,
        ),
        allow_live_broadcast=_boolean(
            value,
            "allow_live_broadcast",
            defaults.allow_live_broadcast,
            path,
        ),
        allowed_privacy_statuses=_strings(
            value,
            "allowed_privacy_statuses",
            defaults.allowed_privacy_statuses,
            path,
        ),
    )


def _load_obs(value: dict[str, Any]) -> ObsSubsystemConfig:
    path = "streaming.obs"
    allowed = {
        "adapter",
        "host",
        "port",
        "password_ref",
        "connect_timeout_seconds",
        "request_timeout_seconds",
        "state_timeout_seconds",
        "poll_interval_seconds",
        "max_retries",
        "retry_initial_delay_seconds",
        "required_audio_sources",
        "optional_audio_sources",
        "avatar_source_name",
        "low_volume_threshold_db",
        "max_scene_depth",
    }
    _reject_unknown(value, allowed, path)
    defaults = ObsSubsystemConfig()
    avatar = value.get("avatar_source_name", defaults.avatar_source_name)
    if avatar is not None and not isinstance(avatar, str):
        raise StreamingConfigError(f"{path}.avatar_source_name", "must_be_string")
    return ObsSubsystemConfig(
        mode=_enum(value, "adapter", ObsAdapterMode, defaults.mode, path),
        host=_string(value, "host", defaults.host, path),
        port=_integer(value, "port", defaults.port, path),
        password_ref=_string(
            value,
            "password_ref",
            defaults.password_ref,
            path,
        ),
        connect_timeout_seconds=_number(
            value,
            "connect_timeout_seconds",
            defaults.connect_timeout_seconds,
            path,
        ),
        request_timeout_seconds=_number(
            value,
            "request_timeout_seconds",
            defaults.request_timeout_seconds,
            path,
        ),
        state_timeout_seconds=_number(
            value,
            "state_timeout_seconds",
            defaults.state_timeout_seconds,
            path,
        ),
        poll_interval_seconds=_number(
            value,
            "poll_interval_seconds",
            defaults.poll_interval_seconds,
            path,
        ),
        max_retries=_integer(value, "max_retries", defaults.max_retries, path),
        retry_initial_delay_seconds=_number(
            value,
            "retry_initial_delay_seconds",
            defaults.retry_initial_delay_seconds,
            path,
        ),
        required_audio_sources=_strings(
            value,
            "required_audio_sources",
            defaults.required_audio_sources,
            path,
        ),
        optional_audio_sources=_strings(
            value,
            "optional_audio_sources",
            defaults.optional_audio_sources,
            path,
        ),
        avatar_source_name=avatar,
        low_volume_threshold_db=_number(
            value,
            "low_volume_threshold_db",
            defaults.low_volume_threshold_db,
            path,
        ),
        max_scene_depth=_integer(
            value,
            "max_scene_depth",
            defaults.max_scene_depth,
            path,
        ),
    )


def _mapping(value: object, path: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) for key in value
    ):
        raise StreamingConfigError(path, "must_be_mapping")
    return dict(value)


def _reject_unknown(value: Mapping[str, object], allowed: set[str], path: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise StreamingConfigError(path, f"unknown_key:{unknown[0]}")


def _enum(
    value: Mapping[str, object],
    key: str,
    enum_type: type[Any],
    default: Any,
    path: str,
) -> Any:
    raw = value.get(key, default.value)
    if not isinstance(raw, str):
        raise StreamingConfigError(f"{path}.{key}", "must_be_string")
    try:
        return enum_type(raw)
    except ValueError as error:
        raise StreamingConfigError(f"{path}.{key}", "invalid_enum") from error


def _string(
    value: Mapping[str, object], key: str, default: str, path: str
) -> str:
    raw = value.get(key, default)
    if not isinstance(raw, str):
        raise StreamingConfigError(f"{path}.{key}", "must_be_string")
    return raw


def _number(
    value: Mapping[str, object], key: str, default: float, path: str
) -> float:
    raw = value.get(key, default)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise StreamingConfigError(f"{path}.{key}", "must_be_number")
    return float(raw)


def _integer(
    value: Mapping[str, object], key: str, default: int, path: str
) -> int:
    raw = value.get(key, default)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise StreamingConfigError(f"{path}.{key}", "must_be_integer")
    return raw


def _boolean(
    value: Mapping[str, object], key: str, default: bool, path: str
) -> bool:
    raw = value.get(key, default)
    if not isinstance(raw, bool):
        raise StreamingConfigError(f"{path}.{key}", "must_be_boolean")
    return raw


def _strings(
    value: Mapping[str, object],
    key: str,
    default: tuple[str, ...],
    path: str,
) -> tuple[str, ...]:
    raw = value.get(key, default)
    if (
        not isinstance(raw, Sequence)
        or isinstance(raw, (str, bytes))
        or any(not isinstance(item, str) for item in raw)
    ):
        raise StreamingConfigError(f"{path}.{key}", "must_be_string_sequence")
    return tuple(raw)
