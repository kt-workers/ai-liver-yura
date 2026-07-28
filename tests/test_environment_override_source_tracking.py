from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.config.config_loader import load_config_bundle
from app.config.environment_override import CONFIG_ENV_ENV
from app.config.errors import ConfigError


_REQUIRED_KEYS = (
    "app",
    "trace",
    "services",
    "models",
    "response_generator",
    "llm_roles",
    "speech",
    "topic_classifier",
    "memory",
    "character",
    "input_receivers",
    "confirmation",
)


def _write_manifest_tree(tmp_path: Path, overrides: list[dict[str, object]]) -> tuple[Path, Path, Path]:
    manifest = tmp_path / "index.yaml"
    owner = tmp_path / "owner.yaml"
    environment = tmp_path / "local.yaml"

    owner_values: dict[str, object] = {
        "app": {"mode": "console", "name": "yura"},
        "trace": {"enabled": False},
        "services": {
            "ollama": {
                "base_url": "http://localhost:11434",
                "timeout_seconds": 30,
            }
        },
        "models": {},
        "response_generator": {},
        "llm_roles": {},
        "speech": {},
        "topic_classifier": {},
        "memory": {},
        "character": {},
        "input_receivers": {},
        "confirmation": {},
    }
    owner.write_text(yaml.safe_dump(owner_values, sort_keys=False), encoding="utf-8")
    environment.write_text(
        yaml.safe_dump({"overrides": overrides}, sort_keys=False),
        encoding="utf-8",
    )
    manifest.write_text(
        yaml.safe_dump(
            {
                "imports": {key: "owner.yaml" for key in _REQUIRED_KEYS},
                "environments": {"local": "local.yaml"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return manifest, owner.resolve(), environment.resolve()


def test_loader_applies_selected_environment_and_tracks_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, owner, environment = _write_manifest_tree(
        tmp_path,
        [
            {"path": "app.mode", "value": "streaming"},
            {
                "path": "services.ollama.base_url",
                "value": "http://ollama.local:11434",
            },
        ],
    )
    monkeypatch.setenv(CONFIG_ENV_ENV, "local")

    bundle = load_config_bundle(manifest)

    assert bundle.values["app"]["mode"] == "streaming"
    assert bundle.values["services"]["ollama"]["base_url"] == "http://ollama.local:11434"
    assert bundle.source_for("app.mode") == environment
    assert bundle.source_for("services.ollama.base_url") == environment
    assert bundle.source_for("app.name") == owner
    assert bundle.source_for("services.ollama.timeout_seconds") == owner
    assert bundle.source_for("unknown.value") == manifest.resolve()


def test_loader_without_environment_preserves_base_values_and_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, owner, _ = _write_manifest_tree(
        tmp_path,
        [{"path": "app.mode", "value": "streaming"}],
    )
    monkeypatch.delenv(CONFIG_ENV_ENV, raising=False)

    bundle = load_config_bundle(manifest)

    assert bundle.values["app"]["mode"] == "console"
    assert bundle.source_by_yaml_path == {}
    assert bundle.source_for("app.mode") == owner


def test_loader_reports_override_application_error_from_environment_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, _, environment = _write_manifest_tree(
        tmp_path,
        [{"path": "app.missing", "value": "streaming"}],
    )
    monkeypatch.setenv(CONFIG_ENV_ENV, "local")

    with pytest.raises(ConfigError) as raised:
        load_config_bundle(manifest)

    assert raised.value.path == "app.missing"
    assert raised.value.source_file == str(environment)


def test_source_for_uses_longest_override_prefix() -> None:
    from types import MappingProxyType

    from app.config.config_loader import ConfigSourceBundle

    root = Path("/config/index.yaml")
    owner = Path("/config/services.yaml")
    broad = Path("/config/environments/broad.yaml")
    narrow = Path("/config/environments/narrow.yaml")
    bundle = ConfigSourceBundle(
        root_path=root,
        values=MappingProxyType({}),
        source_by_top_level_key=MappingProxyType({"services": owner}),
        source_by_yaml_path=MappingProxyType(
            {
                "services.ollama": broad,
                "services.ollama.base_url": narrow,
            }
        ),
    )

    assert bundle.source_for("services.ollama.base_url.detail") == narrow
