from __future__ import annotations

import inspect
from pathlib import Path

import pytest
import yaml

from app.bootstrap import runtime
from app.config.app_config import CONFIG_PATH, load_app_config
from app.config.errors import ConfigError
from app.plugins.games.settings import (
    GamesPluginSettings,
    load_games_plugin_settings,
)


def test_games_settings_are_defined_and_parsed_by_the_plugin() -> None:
    config = load_app_config()
    assert isinstance(config.plugins.games, GamesPluginSettings)
    assert type(config.plugins.games).__module__ == "app.plugins.games.settings"
    source = inspect.getsource(runtime.create_runtime_coordinator)
    assert '"confidence_threshold"' not in source
    assert '"max_generation_retries"' not in source


@pytest.mark.parametrize(
    ("raw", "path"),
    [
        ({"enabled": "false"}, r"plugins\.games\.enabled"),
        (
            {"intent_interpreter": {"confidence_threshold": -0.1}},
            r"confidence_threshold",
        ),
        (
            {"intent_interpreter": {"confidence_threshold": 1.1}},
            r"confidence_threshold",
        ),
        ({"intent_interpreter": {"max_attempts": 0}}, r"max_attempts"),
        ({"shiritori": {"max_generation_retries": -1}}, r"max_generation_retries"),
        ({"shiritori": {"unknown": True}}, r"plugins\.games\.shiritori\.unknown"),
    ],
)
def test_games_plugin_rejects_invalid_own_configuration(
    raw: dict[str, object], path: str
) -> None:
    with pytest.raises(ConfigError, match=path):
        load_games_plugin_settings(raw)


def test_unknown_plugin_configuration_is_opaque_to_core(tmp_path: Path) -> None:
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    raw["plugins"]["sample"] = {
        "plugin_specific_unknown_key": {"nested": [1, "two", False]}
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    config = load_app_config(path)
    assert "sample" in config.plugins.opaque_configs


def test_nonempty_plugin_registry_warns_that_it_is_reserved(tmp_path: Path) -> None:
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    raw["plugins"]["registry"] = {"sample": {"enabled": True}}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    with pytest.warns(FutureWarning, match="予約"):
        config = load_app_config(path)
    assert config.plugins.registrations["sample"].enabled is True
