from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.config.app_config import CONFIG_PATH, load_app_config


def test_retired_plugin_settings_are_not_part_of_core_config() -> None:
    config = load_app_config()
    assert not hasattr(config.plugins, "games")


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
