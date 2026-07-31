from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from subsystems.streaming.config import (
    NullSecretProvider,
    ObsAdapterMode,
    ObsSubsystemConfig,
    StaticSecretProvider,
    StreamingConfigError,
    StreamingSubsystemConfig,
    YouTubeAdapterMode,
    YouTubeSubsystemConfig,
    validate_streaming_subsystem_config,
)


def test_default_config_is_fake_immutable_and_contains_only_secret_refs() -> None:
    config = StreamingSubsystemConfig()

    assert config.youtube.mode is YouTubeAdapterMode.FAKE
    assert config.obs.mode is ObsAdapterMode.FAKE
    assert config.secret_refs.youtube_client_secret_path.startswith("STREAMING_")
    assert config.secret_refs.youtube_token_path.startswith("STREAMING_")
    assert config.secret_refs.obs_password == "STREAMING_OBS_PASSWORD"
    with pytest.raises(FrozenInstanceError):
        config.obs = ObsSubsystemConfig(mode=ObsAdapterMode.DISABLED)


@pytest.mark.parametrize(
    ("youtube_mode", "obs_mode"),
    [
        (YouTubeAdapterMode.FAKE, ObsAdapterMode.FAKE),
        (YouTubeAdapterMode.DISABLED, ObsAdapterMode.DISABLED),
        (YouTubeAdapterMode.FAKE, ObsAdapterMode.DISABLED),
        (YouTubeAdapterMode.DISABLED, ObsAdapterMode.FAKE),
    ],
)
def test_fake_and_disabled_modes_need_no_secrets(
    youtube_mode: YouTubeAdapterMode,
    obs_mode: ObsAdapterMode,
) -> None:
    validate_streaming_subsystem_config(
        StreamingSubsystemConfig(
            youtube=YouTubeSubsystemConfig(mode=youtube_mode),
            obs=ObsSubsystemConfig(mode=obs_mode),
        ),
        NullSecretProvider(),
    )


def test_real_modes_validate_only_named_secret_references() -> None:
    config = StreamingSubsystemConfig(
        youtube=YouTubeSubsystemConfig(mode=YouTubeAdapterMode.GOOGLE),
        obs=ObsSubsystemConfig(mode=ObsAdapterMode.OBS_WEBSOCKET),
    )
    secrets = StaticSecretProvider(
        {
            config.youtube.client_secret_path_ref: "/fixture/client.json",
            config.youtube.token_path_ref: "/fixture/token.json",
            config.obs.password_ref: "fixture-only-value",
        }
    )

    validate_streaming_subsystem_config(config, secrets)
    assert "fixture-only-value" not in repr(config)


@pytest.mark.parametrize(
    "config",
    [
        StreamingSubsystemConfig(obs=ObsSubsystemConfig(port=0)),
        StreamingSubsystemConfig(
            obs=ObsSubsystemConfig(request_timeout_seconds=0)
        ),
        StreamingSubsystemConfig(
            youtube=YouTubeSubsystemConfig(request_timeout_seconds=0)
        ),
        StreamingSubsystemConfig(
            youtube=YouTubeSubsystemConfig(
                allowed_privacy_statuses=("unsupported",)
            )
        ),
    ],
)
def test_invalid_ranges_are_rejected_with_safe_errors(
    config: StreamingSubsystemConfig,
) -> None:
    with pytest.raises(StreamingConfigError) as captured:
        validate_streaming_subsystem_config(config, NullSecretProvider())

    assert "fixture-only-value" not in str(captured.value)
