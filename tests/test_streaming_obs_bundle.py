from __future__ import annotations

import sys
from datetime import datetime, timezone

import pytest

from subsystems.streaming import build_streaming_subsystem
from subsystems.streaming.adapters.obs import (
    DisabledObsPreparationAdapter,
    DisabledObsStreamingControlAdapter,
    FakeObsPreparationAdapter,
    FakeObsStreamingControlAdapter,
    ObsWebSocketPreparationAdapter,
    ObsWebSocketStreamingControlAdapter,
    build_obs_adapter_bundle,
)
from subsystems.streaming.config import (
    ObsAdapterMode,
    ObsSubsystemConfig,
    YouTubeAdapterMode,
    YouTubeSubsystemConfig,
)

NOW = datetime(2026, 7, 31, tzinfo=timezone.utc)


def test_composition_selects_fake_real_and_disabled_obs_bundles() -> None:
    fake = build_obs_adapter_bundle(ObsSubsystemConfig())
    assert fake.mode is ObsAdapterMode.FAKE
    assert isinstance(fake.preparation, FakeObsPreparationAdapter)
    assert isinstance(fake.control, FakeObsStreamingControlAdapter)

    sdk_module = sys.modules.get("obsws_python")
    real = build_obs_adapter_bundle(
        ObsSubsystemConfig(
            mode=ObsAdapterMode.OBS_WEBSOCKET,
            password_env="OBS_PASSWORD",
        )
    )
    assert real.mode is ObsAdapterMode.OBS_WEBSOCKET
    assert isinstance(real.preparation, ObsWebSocketPreparationAdapter)
    assert isinstance(real.control, ObsWebSocketStreamingControlAdapter)
    assert sys.modules.get("obsws_python") is sdk_module

    disabled = build_obs_adapter_bundle(
        ObsSubsystemConfig(mode=ObsAdapterMode.DISABLED)
    )
    assert isinstance(disabled.preparation, DisabledObsPreparationAdapter)
    assert isinstance(disabled.control, DisabledObsStreamingControlAdapter)


def test_real_obs_bundle_requires_only_secret_environment_variable_name() -> None:
    with pytest.raises(ValueError, match="environment variable name"):
        build_obs_adapter_bundle(
            ObsSubsystemConfig(mode=ObsAdapterMode.OBS_WEBSOCKET)
        )


@pytest.mark.asyncio
async def test_obs_and_youtube_bundles_can_be_disabled_independently() -> None:
    obs_disabled = build_streaming_subsystem(
        clock=lambda: NOW,
        obs_config=ObsSubsystemConfig(mode=ObsAdapterMode.DISABLED),
        youtube_config=YouTubeSubsystemConfig(mode=YouTubeAdapterMode.FAKE),
    )
    health = await obs_disabled.get_health()
    assert health.components == {
        "runtime": True,
        "obs": False,
        "youtube": True,
        "tts": False,
        "avatar": False,
    }

    youtube_disabled = build_streaming_subsystem(
        clock=lambda: NOW,
        obs_config=ObsSubsystemConfig(mode=ObsAdapterMode.FAKE),
        youtube_config=YouTubeSubsystemConfig(mode=YouTubeAdapterMode.DISABLED),
    )
    health = await youtube_disabled.get_health()
    assert health.components == {
        "runtime": True,
        "obs": True,
        "youtube": False,
        "tts": False,
        "avatar": False,
    }


@pytest.mark.asyncio
async def test_fake_obs_control_supports_state_scene_and_input_operations() -> None:
    control = FakeObsStreamingControlAdapter(statuses=["idle", "active"])
    await control.start_stream()
    await control.set_current_scene("Live")
    await control.set_input_mute("Mic", True)

    assert control.start_calls == 1
    assert control.current_scene == "Live"
    assert control.muted_inputs == {"Mic": True}

    control.statuses = ["active", "idle"]
    await control.stop_stream()
    assert control.stop_calls == 1
