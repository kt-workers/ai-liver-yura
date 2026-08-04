from __future__ import annotations

import importlib
from dataclasses import replace

import pytest

from app.bootstrap.runtime_plugin_setup import (
    RuntimePluginSetupInput,
    setup_runtime_plugins,
)
from app.config.app_config import load_app_config
from app.domain.activities import Activity
from app.ports.avatar_output import bind_avatar_output, get_bound_avatar_output
from app.runtime.activity_manager import ActivityManager


class _ResponseGenerator:
    async def generate_response(self, activity: Activity) -> str:
        return "response"


def _setup_input() -> RuntimePluginSetupInput:
    config = load_app_config()
    config = replace(
        config,
        response_generator=replace(config.response_generator, type="dummy"),
    )
    return RuntimePluginSetupInput(
        config=config,
        activity_manager=ActivityManager(),
        raw_response_generator=_ResponseGenerator(),
        raw_situation_generator=_ResponseGenerator(),
        raw_character_generator=None,
        raw_validator_generator=None,
        raw_relationship_memory_store=None,
        raw_agent_memory_store=None,
        speech_synthesizer=None,
        audio_player=None,
    )


@pytest.fixture(autouse=True)
def reset_avatar_output_binding() -> None:
    bind_avatar_output(None)
    yield
    bind_avatar_output(None)


def test_disabled_avatar_output_is_not_imported_or_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("YURA_AVATAR_OUTPUT_ENABLED", raising=False)
    monkeypatch.delenv("YURA_AVATAR_RUNTIME_URL", raising=False)
    original_import_module = importlib.import_module

    def import_module(name: str, package: str | None = None) -> object:
        if name == "app.plugins.avatar_output":
            raise AssertionError("無効なAvatar Output Pluginをimportしました")
        return original_import_module(name, package)

    monkeypatch.setattr(
        "app.core.plugins.plugin_loader.importlib.import_module",
        import_module,
    )

    services = setup_runtime_plugins(_setup_input())

    assert services.plugin_manager.get_plugin("avatar_output") is None
    assert get_bound_avatar_output() is None


def test_enabled_avatar_output_is_registered_and_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YURA_AVATAR_OUTPUT_ENABLED", "1")
    monkeypatch.setenv("YURA_AVATAR_RUNTIME_URL", "https://avatar.example.test")

    services = setup_runtime_plugins(_setup_input())
    plugin = services.plugin_manager.get_plugin("avatar_output")

    assert plugin is not None
    assert services.plugin_manager.is_capability_available(
        "output.avatar.expression",
        "avatar_output",
    )
    assert services.plugin_manager.is_capability_available(
        "output.avatar.gesture",
        "avatar_output",
    )
    assert services.plugin_manager.is_capability_available(
        "output.avatar.gaze",
        "avatar_output",
    )
    assert get_bound_avatar_output() is plugin
