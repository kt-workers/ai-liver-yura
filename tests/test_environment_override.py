from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.config.config_loader import (
    DEFAULT_CONFIG_PATH,
    LEGACY_CONFIG_PATH,
    load_config_bundle,
    load_raw_config,
)
from app.config.environment_override import (
    CONFIG_ENV_ENV,
    parse_environment_paths,
    reject_legacy_environment,
    resolve_config_environment,
    resolve_environment_file,
)
from app.config.errors import ConfigError


def test_unset_environment_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CONFIG_ENV_ENV, raising=False)
    assert resolve_config_environment() is None


def test_blank_environment_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CONFIG_ENV_ENV, "   ")
    assert resolve_config_environment() is None


def test_valid_environment_is_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CONFIG_ENV_ENV, " local-test_1 ")
    assert resolve_config_environment() == "local-test_1"


@pytest.mark.parametrize("value", ["LOCAL", "local.test", "../local", "local test"])
def test_invalid_environment_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv(CONFIG_ENV_ENV, value)
    with pytest.raises(ConfigError, match=CONFIG_ENV_ENV):
        resolve_config_environment()


def test_environment_paths_are_relative_to_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "index.yaml"
    expected = (tmp_path / "environments" / "local.yaml").resolve()

    environments = parse_environment_paths(
        manifest,
        {"local": "environments/local.yaml"},
    )

    assert environments == {"local": expected}


def test_missing_environments_defaults_to_empty(tmp_path: Path) -> None:
    assert parse_environment_paths(tmp_path / "index.yaml", None) == {}


@pytest.mark.parametrize("value", [[], "local.yaml", 1])
def test_environments_must_be_mapping(tmp_path: Path, value: object) -> None:
    manifest = tmp_path / "index.yaml"
    with pytest.raises(ConfigError) as raised:
        parse_environment_paths(manifest, value)
    assert raised.value.source_file == str(manifest)


def test_invalid_manifest_environment_name_is_rejected(tmp_path: Path) -> None:
    manifest = tmp_path / "index.yaml"
    with pytest.raises(ConfigError, match=r"environments\.Local") as raised:
        parse_environment_paths(manifest, {"Local": "local.yaml"})
    assert raised.value.source_file == str(manifest)


def test_blank_environment_path_is_rejected(tmp_path: Path) -> None:
    manifest = tmp_path / "index.yaml"
    with pytest.raises(ConfigError, match=r"environments\.local") as raised:
        parse_environment_paths(manifest, {"local": "   "})
    assert raised.value.source_file == str(manifest)


def test_registered_environment_file_is_resolved(tmp_path: Path) -> None:
    manifest = tmp_path / "index.yaml"
    target = tmp_path / "local.yaml"
    target.write_text("overrides: []\n", encoding="utf-8")

    resolved = resolve_environment_file(manifest, {"local": target}, "local")

    assert resolved == target


def test_unregistered_environment_is_rejected(tmp_path: Path) -> None:
    manifest = tmp_path / "index.yaml"
    with pytest.raises(ConfigError, match=CONFIG_ENV_ENV) as raised:
        resolve_environment_file(manifest, {}, "local")
    assert raised.value.source_file == str(manifest)


def test_missing_environment_file_is_rejected(tmp_path: Path) -> None:
    manifest = tmp_path / "index.yaml"
    missing = tmp_path / "missing.yaml"
    with pytest.raises(ConfigError, match="actual=missing") as raised:
        resolve_environment_file(manifest, {"local": missing}, "local")
    assert raised.value.source_file == str(missing)


def test_environment_path_must_be_file(tmp_path: Path) -> None:
    manifest = tmp_path / "index.yaml"
    directory = tmp_path / "local"
    directory.mkdir()
    with pytest.raises(ConfigError, match="actual=directory"):
        resolve_environment_file(manifest, {"local": directory}, "local")


def test_no_selected_environment_skips_file_resolution(tmp_path: Path) -> None:
    assert resolve_environment_file(tmp_path / "index.yaml", {}, None) is None


def test_legacy_entry_rejects_selected_environment(tmp_path: Path) -> None:
    legacy = tmp_path / "config.yaml"
    with pytest.raises(ConfigError, match=CONFIG_ENV_ENV) as raised:
        reject_legacy_environment(legacy, "local")
    assert raised.value.source_file == str(legacy)


def test_legacy_entry_allows_no_environment(tmp_path: Path) -> None:
    reject_legacy_environment(tmp_path / "config.yaml", None)


def _write_manifest_with_environment(tmp_path: Path) -> Path:
    manifest = load_raw_config(DEFAULT_CONFIG_PATH)
    imports = manifest["imports"]
    manifest["imports"] = {
        key: str((DEFAULT_CONFIG_PATH.parent / path).resolve())
        for key, path in imports.items()
    }
    environment_file = tmp_path / "local.yaml"
    environment_file.write_text("overrides: []\n", encoding="utf-8")
    manifest["environments"] = {"local": environment_file.name}
    index = tmp_path / "index.yaml"
    index.write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return index


def test_loader_accepts_registered_environment_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index = _write_manifest_with_environment(tmp_path)
    monkeypatch.setenv(CONFIG_ENV_ENV, "local")

    bundle = load_config_bundle(index)

    assert bundle.root_path == index.resolve()
    assert bundle.values["app"]


def test_loader_rejects_unregistered_selected_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index = _write_manifest_with_environment(tmp_path)
    monkeypatch.setenv(CONFIG_ENV_ENV, "missing")

    with pytest.raises(ConfigError, match=CONFIG_ENV_ENV) as raised:
        load_config_bundle(index)

    assert raised.value.source_file == str(index.resolve())


def test_loader_rejects_legacy_entry_with_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CONFIG_ENV_ENV, "local")

    with pytest.raises(ConfigError, match=CONFIG_ENV_ENV) as raised:
        load_config_bundle(LEGACY_CONFIG_PATH)

    assert raised.value.source_file == str(LEGACY_CONFIG_PATH.resolve())
