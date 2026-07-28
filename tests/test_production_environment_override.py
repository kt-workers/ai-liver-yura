from __future__ import annotations

from pathlib import Path

import pytest

from app.config.config_loader import DEFAULT_CONFIG_PATH, load_config_bundle
from app.config.environment_override import CONFIG_ENV_ENV


def test_production_manifest_registers_runnable_local_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CONFIG_ENV_ENV, "local")

    bundle = load_config_bundle(DEFAULT_CONFIG_PATH)
    environment_file = (
        DEFAULT_CONFIG_PATH.parent / "environments" / "local.example.yaml"
    ).resolve()
    runtime_file = (DEFAULT_CONFIG_PATH.parent / "runtime.yaml").resolve()

    assert bundle.values["trace"]["level"] == "DEBUG"
    assert bundle.values["trace"]["debug_file_enabled"] is True
    assert bundle.values["input_receivers"]["timer"]["interval_seconds"] == 5.0

    assert bundle.source_for("trace.level") == environment_file
    assert bundle.source_for("trace.debug_file_enabled") == environment_file
    assert (
        bundle.source_for("input_receivers.timer.interval_seconds")
        == environment_file
    )
    assert bundle.source_for("trace.format") == runtime_file


def test_production_manifest_keeps_base_values_without_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(CONFIG_ENV_ENV, raising=False)

    bundle = load_config_bundle(DEFAULT_CONFIG_PATH)
    runtime_file = (DEFAULT_CONFIG_PATH.parent / "runtime.yaml").resolve()

    assert bundle.values["trace"]["level"] == "INFO"
    assert bundle.values["input_receivers"]["timer"]["interval_seconds"] == 30.0
    assert bundle.source_for("trace.level") == runtime_file
