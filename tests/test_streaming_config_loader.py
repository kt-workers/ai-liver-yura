from __future__ import annotations

from pathlib import Path

import pytest

from subsystems.streaming.config import (
    ObsAdapterMode,
    StaticSecretProvider,
    StreamingConfigError,
    YouTubeAdapterMode,
    load_streaming_subsystem_config,
)


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "nested" / "streaming.yaml"
    path.parent.mkdir()
    path.write_text(text, encoding="utf-8")
    return path


def test_loader_reads_yaml_converts_types_and_normalizes_source_path(
    tmp_path: Path,
) -> None:
    path = _write(
        tmp_path,
        """
streaming:
  youtube:
    adapter: google
    client_secret_path_ref: CLIENT_REF
    token_path_ref: TOKEN_REF
    request_timeout_seconds: 12
    max_retries: 3
    oauth_open_browser: false
  obs:
    adapter: obs_websocket
    host: localhost
    port: 4456
    password_ref: OBS_REF
    required_audio_sources: [Mic, BGM]
""",
    )
    config = load_streaming_subsystem_config(
        path,
        environ={},
        secret_provider=StaticSecretProvider(
            {
                "CLIENT_REF": "/fixture/client.json",
                "TOKEN_REF": "/fixture/token.json",
                "OBS_REF": "fixture-only-value",
            }
        ),
    )

    assert config.source_path == path.resolve()
    assert config.youtube.mode is YouTubeAdapterMode.GOOGLE
    assert config.youtube.request_timeout_seconds == 12.0
    assert config.youtube.max_retries == 3
    assert config.youtube.oauth_open_browser is False
    assert config.obs.mode is ObsAdapterMode.OBS_WEBSOCKET
    assert config.obs.port == 4456
    assert config.obs.required_audio_sources == ("Mic", "BGM")


def test_environment_override_has_explicit_type_conversion(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
streaming:
  youtube:
    adapter: fake
  obs:
    adapter: fake
""",
    )
    config = load_streaming_subsystem_config(
        path,
        environ={
            "STREAMING_YOUTUBE_ADAPTER": "disabled",
            "STREAMING_YOUTUBE_MAX_RETRIES": "7",
            "STREAMING_YOUTUBE_OAUTH_OPEN_BROWSER": "false",
            "STREAMING_OBS_PORT": "4457",
            "STREAMING_OBS_REQUIRED_AUDIO_SOURCES": "Mic, BGM",
        },
    )

    assert config.youtube.mode is YouTubeAdapterMode.DISABLED
    assert config.youtube.max_retries == 7
    assert config.youtube.oauth_open_browser is False
    assert config.obs.port == 4457
    assert config.obs.required_audio_sources == ("Mic", "BGM")


def test_loader_defaults_omitted_youtube_or_obs_sections(tmp_path: Path) -> None:
    youtube_only = _write(
        tmp_path,
        "streaming: {youtube: {adapter: disabled}}",
    )
    config = load_streaming_subsystem_config(youtube_only, environ={})

    assert config.youtube.mode is YouTubeAdapterMode.DISABLED
    assert config.obs.mode is ObsAdapterMode.FAKE


@pytest.mark.parametrize(
    "body",
    [
        "streaming: {youtube: {adapter: unknown}, obs: {adapter: fake}}",
        "streaming: {youtube: {adapter: fake, extra: true}, obs: {adapter: fake}}",
        "streaming: {youtube: {adapter: fake}, obs: {adapter: fake, port: text}}",
        "streaming: []",
    ],
)
def test_loader_rejects_invalid_enum_unknown_key_and_wrong_type(
    tmp_path: Path,
    body: str,
) -> None:
    path = _write(tmp_path, body)
    with pytest.raises(StreamingConfigError):
        load_streaming_subsystem_config(path, environ={})


def test_loader_treats_real_secret_absence_as_error_only_when_resolving(
    tmp_path: Path,
) -> None:
    path = _write(
        tmp_path,
        """
streaming:
  youtube: {adapter: google}
  obs: {adapter: disabled}
""",
    )

    unresolved = load_streaming_subsystem_config(path, environ={})
    assert unresolved.youtube.mode is YouTubeAdapterMode.GOOGLE
    with pytest.raises(StreamingConfigError, match="required_secret_missing"):
        load_streaming_subsystem_config(
            path,
            environ={},
            secret_provider=StaticSecretProvider({}),
        )
