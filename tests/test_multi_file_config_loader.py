from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.config import config_loader
from app.config.app_config import CONFIG_PATH, load_app_config, load_raw_config
from app.config.config_loader import (
    CONFIG_PATH_ENV,
    DEFAULT_CONFIG_PATH,
    ConfigSourceBundle,
)
from app.config.errors import ConfigError
from app.config.service_schema import OpenAiServiceSettings

_FILE_OWNERS = {
    "runtime.yaml": ("app", "trace", "input_receivers", "confirmation"),
    "services.yaml": ("services",),
    "models.yaml": (
        "models",
        "response_generator",
        "llm_roles",
        "topic_classifier",
    ),
    "speech.yaml": ("speech",),
    "memory.yaml": ("memory",),
    "character.yaml": ("character",),
    "streaming.yaml": ("streaming",),
    "plugins.yaml": ("plugins",),
}


def _write_yaml(path: Path, value: object) -> None:
    path.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _read_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _write_split_config(directory: Path) -> Path:
    directory.mkdir()
    legacy = load_raw_config(CONFIG_PATH)
    imports: dict[str, str] = {}
    for file_name, keys in _FILE_OWNERS.items():
        values = {key: legacy[key] for key in keys}
        _write_yaml(directory / file_name, values)
        imports.update({key: file_name for key in keys})
    index = directory / "index.yaml"
    _write_yaml(index, {"imports": imports})
    return index


@pytest.fixture
def split_config(tmp_path: Path) -> Path:
    return _write_split_config(tmp_path / "config_split")


def test_legacy_and_split_configs_are_equivalent(split_config: Path) -> None:
    legacy = load_app_config(CONFIG_PATH)
    split = load_app_config(split_config)

    assert replace(legacy, config_path="") == replace(split, config_path="")
    assert type(legacy.services["openai"]) is type(split.services["openai"])
    assert isinstance(split.services["openai"], OpenAiServiceSettings)
    assert type(legacy.services) is type(split.services)
    assert type(legacy.character.likes) is type(split.character.likes)
    assert legacy.plugins == split.plugins
    assert legacy.streaming == split.streaming


def test_manifest_can_assign_every_key_to_its_own_file(tmp_path: Path) -> None:
    directory = tmp_path / "one-key-per-file"
    directory.mkdir()
    legacy = load_raw_config(CONFIG_PATH)
    imports: dict[str, str] = {}
    for key, value in legacy.items():
        path = directory / f"{key}.yaml"
        _write_yaml(path, {key: value})
        imports[key] = path.name
    index = directory / "index.yaml"
    _write_yaml(index, {"imports": imports})

    assert replace(load_app_config(index), config_path="") == replace(
        load_app_config(CONFIG_PATH),
        config_path="",
    )


def test_directory_input_resolves_index_yaml(split_config: Path) -> None:
    config = load_app_config(split_config.parent)
    assert config.config_path == str(split_config.resolve())


def test_manifest_accepts_absolute_import_path(split_config: Path) -> None:
    manifest = _read_yaml(split_config)
    manifest["imports"]["services"] = str(
        (split_config.parent / "services.yaml").resolve()
    )
    _write_yaml(split_config, manifest)

    assert isinstance(
        load_app_config(split_config).services["openai"],
        OpenAiServiceSettings,
    )


def test_manifest_reads_shared_import_only_once(
    split_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = config_loader.load_raw_config
    calls: list[Path] = []

    def tracked(path: str | Path = CONFIG_PATH) -> dict[str, Any]:
        calls.append(Path(path).resolve())
        return original(path)

    monkeypatch.setattr(config_loader, "load_raw_config", tracked)
    config_loader.load_config_bundle(split_config)

    runtime = (split_config.parent / "runtime.yaml").resolve()
    assert calls.count(runtime) == 1


def test_bundle_keeps_immutable_top_level_source_map(split_config: Path) -> None:
    bundle = config_loader.load_config_bundle(split_config)
    assert isinstance(bundle, ConfigSourceBundle)
    assert bundle.root_path == split_config.resolve()
    assert bundle.source_for("models.openai_chat.name") == (
        split_config.parent / "models.yaml"
    ).resolve()
    with pytest.raises(TypeError):
        bundle.source_by_top_level_key["models"] = split_config  # type: ignore[index]


@pytest.mark.parametrize("value", [None, 123, "", "   "])
def test_manifest_rejects_invalid_import_values(
    tmp_path: Path,
    value: object,
) -> None:
    index = tmp_path / "index.yaml"
    _write_yaml(index, {"imports": {"app": value}})
    with pytest.raises(ConfigError, match=r"path=imports\.app") as raised:
        config_loader.load_config_bundle(index)
    assert raised.value.source_file == str(index.resolve())


@pytest.mark.parametrize(
    ("contents", "path"),
    [
        ({"imports": []}, "imports"),
        ({"imports": {}, "app": {}}, "app"),
        ({"imports": {"unknown": "unknown.yaml"}}, "imports.unknown"),
    ],
)
def test_manifest_rejects_invalid_structure(
    tmp_path: Path,
    contents: object,
    path: str,
) -> None:
    index = tmp_path / "index.yaml"
    _write_yaml(index, contents)
    with pytest.raises(ConfigError, match=rf"path={re.escape(path)}") as raised:
        config_loader.load_config_bundle(index)
    assert raised.value.source_file == str(index.resolve())


def test_manifest_reports_missing_required_assignment(tmp_path: Path) -> None:
    app = tmp_path / "app.yaml"
    _write_yaml(app, {"app": {"name": "test", "mode": "console"}})
    index = tmp_path / "index.yaml"
    _write_yaml(index, {"imports": {"app": "app.yaml"}})

    with pytest.raises(ConfigError, match=r"path=imports\.character") as raised:
        config_loader.load_config_bundle(index)
    assert raised.value.source_file == str(index.resolve())


def test_directory_requires_manifest_index(tmp_path: Path) -> None:
    directory = tmp_path / "config"
    directory.mkdir()
    with pytest.raises(ConfigError, match="index.yaml missing"):
        config_loader.load_config_bundle(directory)


def test_directory_rejects_index_yaml_directory(tmp_path: Path) -> None:
    directory = tmp_path / "config"
    (directory / "index.yaml").mkdir(parents=True)
    with pytest.raises(ConfigError, match="index.yaml is not a file"):
        config_loader.load_config_bundle(directory)


def test_index_yaml_is_manifest_only(tmp_path: Path) -> None:
    index = tmp_path / "index.yaml"
    _write_yaml(index, load_raw_config(CONFIG_PATH))
    with pytest.raises(ConfigError, match=r"path=imports"):
        config_loader.load_config_bundle(index)


def test_low_level_raw_loader_does_not_resolve_manifest(
    split_config: Path,
) -> None:
    assert load_raw_config(split_config) == _read_yaml(split_config)


def test_import_target_must_exist(split_config: Path) -> None:
    manifest = _read_yaml(split_config)
    manifest["imports"]["services"] = "missing.yaml"
    _write_yaml(split_config, manifest)
    with pytest.raises(ConfigError, match="actual=missing") as raised:
        config_loader.load_config_bundle(split_config)
    assert raised.value.source_file == str(
        (split_config.parent / "missing.yaml").resolve()
    )


def test_import_target_must_be_file(split_config: Path) -> None:
    target = split_config.parent / "services-directory"
    target.mkdir()
    manifest = _read_yaml(split_config)
    manifest["imports"]["services"] = target.name
    _write_yaml(split_config, manifest)
    with pytest.raises(ConfigError, match="actual=directory"):
        config_loader.load_config_bundle(split_config)


def test_import_target_root_must_be_mapping(split_config: Path) -> None:
    services = split_config.parent / "services.yaml"
    _write_yaml(services, ["not", "a", "mapping"])
    with pytest.raises(ConfigError, match="expected=object") as raised:
        config_loader.load_config_bundle(split_config)
    assert raised.value.source_file == str(services.resolve())


def test_import_target_yaml_syntax_error_has_import_source(
    split_config: Path,
) -> None:
    services = split_config.parent / "services.yaml"
    services.write_text("services: [\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="valid YAML syntax") as raised:
        config_loader.load_config_bundle(split_config)
    assert raised.value.source_file == str(services.resolve())


def test_nested_imports_are_rejected(split_config: Path) -> None:
    services = split_config.parent / "services.yaml"
    _write_yaml(services, {"imports": {"services": "other.yaml"}})
    with pytest.raises(ConfigError, match="nested or circular import") as raised:
        config_loader.load_config_bundle(split_config)
    assert raised.value.source_file == str(services.resolve())


def test_manifest_cannot_import_itself(split_config: Path) -> None:
    manifest = _read_yaml(split_config)
    manifest["imports"]["services"] = "./index.yaml"
    _write_yaml(split_config, manifest)
    with pytest.raises(ConfigError, match="circular import") as raised:
        config_loader.load_config_bundle(split_config)
    assert str(split_config.resolve()) in str(raised.value)


def test_manifest_detects_symlink_to_itself(split_config: Path) -> None:
    link = split_config.parent / "self.yaml"
    try:
        link.symlink_to(split_config.name)
    except OSError:
        pytest.skip("symlinks are not available")
    manifest = _read_yaml(split_config)
    manifest["imports"]["services"] = link.name
    _write_yaml(split_config, manifest)
    with pytest.raises(ConfigError, match="circular import"):
        config_loader.load_config_bundle(split_config)


def test_imported_file_cannot_contain_unowned_key(split_config: Path) -> None:
    runtime = split_config.parent / "runtime.yaml"
    values = _read_yaml(runtime)
    values["services"] = {}
    _write_yaml(runtime, values)
    with pytest.raises(ConfigError, match="unexpected key services") as raised:
        config_loader.load_config_bundle(split_config)
    assert raised.value.source_file == str(runtime.resolve())


def test_imported_file_must_contain_assigned_key(split_config: Path) -> None:
    runtime = split_config.parent / "runtime.yaml"
    values = _read_yaml(runtime)
    del values["app"]
    _write_yaml(runtime, values)
    with pytest.raises(ConfigError, match=r"path=imports\.app") as raised:
        config_loader.load_config_bundle(split_config)
    assert raised.value.source_file == str(runtime.resolve())


def test_duplicate_manifest_key_is_rejected(tmp_path: Path) -> None:
    index = tmp_path / "index.yaml"
    index.write_text(
        "imports:\n  app: a.yaml\n  app: b.yaml\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="unique mapping keys") as raised:
        config_loader.load_config_bundle(index)
    assert raised.value.source_file == str(index.resolve())


def test_manifest_yaml_syntax_error_has_manifest_source(tmp_path: Path) -> None:
    index = tmp_path / "index.yaml"
    index.write_text("imports: [\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="valid YAML syntax") as raised:
        config_loader.load_config_bundle(index)
    assert raised.value.source_file == str(index.resolve())


@pytest.mark.parametrize(
    ("file_name", "change", "expected_path"),
    [
        (
            "services.yaml",
            lambda raw: raw["services"]["voicevox"].update(
                timeout_seconds="invalid"
            ),
            "services.voicevox.timeout_seconds",
        ),
        (
            "models.yaml",
            lambda raw: raw["models"]["openai_chat"].update(service="missing"),
            "models.openai_chat.service",
        ),
        (
            "speech.yaml",
            lambda raw: raw["speech"].update(service="missing"),
            "speech.service",
        ),
    ],
)
def test_app_config_errors_use_import_owner_as_source(
    split_config: Path,
    file_name: str,
    change: Any,
    expected_path: str,
) -> None:
    source = split_config.parent / file_name
    values = _read_yaml(source)
    change(values)
    _write_yaml(source, values)
    with pytest.raises(
        ConfigError,
        match=rf"path={re.escape(expected_path)}",
    ) as raised:
        load_app_config(split_config)
    assert raised.value.source_file == str(source.resolve())


def test_environment_variable_selects_single_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CONFIG_PATH_ENV, str(CONFIG_PATH))
    assert load_app_config().config_path == str(CONFIG_PATH.resolve())


def test_unset_environment_uses_production_manifest_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(CONFIG_PATH_ENV, raising=False)
    assert load_app_config().config_path == str(DEFAULT_CONFIG_PATH.resolve())


def test_environment_variable_selects_manifest(
    split_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CONFIG_PATH_ENV, str(split_config))
    assert load_app_config().config_path == str(split_config.resolve())


def test_environment_variable_selects_directory(
    split_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CONFIG_PATH_ENV, str(split_config.parent))
    assert load_app_config().config_path == str(split_config.resolve())


def test_environment_relative_path_uses_working_directory(
    split_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(split_config.parent.parent)
    monkeypatch.setenv(CONFIG_PATH_ENV, split_config.parent.name)
    assert load_app_config().config_path == str(split_config.resolve())


def test_environment_missing_path_is_clear_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = tmp_path / "missing.yaml"
    monkeypatch.setenv(CONFIG_PATH_ENV, str(missing))
    with pytest.raises(ConfigError, match="actual=missing") as raised:
        load_app_config()
    assert raised.value.source_file == str(missing.resolve())


def test_empty_environment_value_uses_production_manifest_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CONFIG_PATH_ENV, "   ")
    assert load_app_config().config_path == str(DEFAULT_CONFIG_PATH.resolve())


def test_explicit_argument_has_priority_over_environment(
    split_config: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CONFIG_PATH_ENV, str(tmp_path / "missing.yaml"))
    assert load_app_config(split_config).config_path == str(split_config.resolve())


def test_string_path_remains_supported(split_config: Path) -> None:
    assert load_app_config(str(split_config)).config_path == str(split_config.resolve())
