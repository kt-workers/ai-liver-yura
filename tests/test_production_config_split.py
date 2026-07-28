from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.bootstrap import (
    compose_streaming,
    create_runtime_coordinator,
    create_stream_preparation_runtime,
)
from app.bootstrap.runtime import create_speech_synthesizer
from app.bootstrap.runtime_preflight import validate_runtime_service_settings
from app.config.app_config import load_app_config, load_raw_config
from app.config.config_loader import (
    CONFIG_DIRECTORY,
    CONFIG_PATH_ENV,
    DEFAULT_CONFIG_PATH,
    LEGACY_CONFIG_PATH,
    load_config_bundle,
)
from app.config.errors import ConfigError
from app.config.service_schema import OpenAiServiceSettings

RUNTIME_PATH = CONFIG_DIRECTORY / "runtime.yaml"
CHARACTER_PATH = CONFIG_DIRECTORY / "character.yaml"
SPEECH_PATH = CONFIG_DIRECTORY / "speech.yaml"
MEMORY_PATH = CONFIG_DIRECTORY / "memory.yaml"
SERVICES_PATH = CONFIG_DIRECTORY / "services.yaml"
MODELS_PATH = CONFIG_DIRECTORY / "models.yaml"
APPLICATION_PATH = CONFIG_DIRECTORY / "application.yaml"


def test_production_yaml_files_are_valid_mappings() -> None:
    expected_keys = {
        DEFAULT_CONFIG_PATH: {"imports"},
        RUNTIME_PATH: {"app", "trace", "input_receivers", "confirmation"},
        CHARACTER_PATH: {"character"},
        SPEECH_PATH: {"speech"},
        MEMORY_PATH: {"memory"},
        SERVICES_PATH: {"services"},
        MODELS_PATH: {"models"},
        APPLICATION_PATH: {
            "response_generator",
            "llm_roles",
            "topic_classifier",
            "streaming",
            "plugins",
        },
    }
    for path, keys in expected_keys.items():
        assert set(load_raw_config(path)) == keys


def test_production_manifest_loads_successfully() -> None:
    config = load_app_config(DEFAULT_CONFIG_PATH)
    validate_runtime_service_settings(config)

    assert config.app.name == "ai-liver"
    assert config.character.name == "星波ゆら"
    assert isinstance(config.services["openai"], OpenAiServiceSettings)
    assert config.config_path == str(DEFAULT_CONFIG_PATH.resolve())


def test_production_manifest_matches_legacy_config() -> None:
    legacy = load_app_config(LEGACY_CONFIG_PATH)
    production = load_app_config(DEFAULT_CONFIG_PATH)
    production_raw = load_config_bundle(DEFAULT_CONFIG_PATH)

    assert production_raw.values == load_raw_config(LEGACY_CONFIG_PATH)
    assert replace(legacy, config_path="") == replace(production, config_path="")
    assert type(legacy.services) is type(production.services)
    assert type(legacy.speech.voice_intent_profiles) is type(
        production.speech.voice_intent_profiles
    )
    assert type(legacy.character.likes) is type(production.character.likes)
    assert legacy.models == production.models
    assert legacy.speech == production.speech
    assert legacy.memory == production.memory
    assert legacy.input_receivers == production.input_receivers
    assert legacy.confirmation == production.confirmation
    assert legacy.streaming == production.streaming
    assert legacy.plugins == production.plugins


def test_production_manifest_ownership_sources() -> None:
    bundle = load_config_bundle(DEFAULT_CONFIG_PATH)

    for key in ("app", "trace", "input_receivers", "confirmation"):
        assert bundle.source_by_top_level_key[key] == RUNTIME_PATH.resolve()
    assert bundle.source_by_top_level_key["character"] == CHARACTER_PATH.resolve()
    assert bundle.source_by_top_level_key["speech"] == SPEECH_PATH.resolve()
    assert bundle.source_by_top_level_key["memory"] == MEMORY_PATH.resolve()
    assert bundle.source_by_top_level_key["services"] == SERVICES_PATH.resolve()
    assert bundle.source_by_top_level_key["models"] == MODELS_PATH.resolve()
    for key in (
        "response_generator",
        "llm_roles",
        "topic_classifier",
        "streaming",
        "plugins",
    ):
        assert bundle.source_by_top_level_key[key] == APPLICATION_PATH.resolve()


def test_default_config_entry_loads_production_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(CONFIG_PATH_ENV, raising=False)
    config = load_app_config()
    assert Path(config.config_path) == DEFAULT_CONFIG_PATH.resolve()


def test_legacy_file_and_config_directory_remain_supported() -> None:
    legacy = load_app_config(LEGACY_CONFIG_PATH)
    directory = load_app_config(CONFIG_DIRECTORY)

    assert Path(legacy.config_path) == LEGACY_CONFIG_PATH.resolve()
    assert Path(directory.config_path) == DEFAULT_CONFIG_PATH.resolve()
    assert replace(legacy, config_path="") == replace(directory, config_path="")


def test_production_config_composes_runtime_streaming_speech_and_admin() -> None:
    config = load_app_config(DEFAULT_CONFIG_PATH)
    validate_runtime_service_settings(config)
    assert create_speech_synthesizer(config) is not None

    streaming_runtime = create_stream_preparation_runtime(config)
    composition = compose_streaming(streaming_runtime)
    assert Path(streaming_runtime.config.config_path) == DEFAULT_CONFIG_PATH.resolve()
    assert composition.admin_api.runtime_status()["config_path"] == str(
        DEFAULT_CONFIG_PATH.resolve()
    )

    safe_runtime_config = replace(
        config,
        response_generator=replace(config.response_generator, type="dummy"),
        speech=replace(config.speech, enabled=False),
        memory=replace(
            config.memory,
            topic_memory=replace(config.memory.topic_memory, enabled=False),
        ),
    )
    assert create_runtime_coordinator(safe_runtime_config) is not None


@pytest.mark.parametrize(
    ("file_name", "change", "error_path"),
    [
        (
            "speech.yaml",
            lambda raw: raw["speech"].update(service="unknown_voice_service"),
            "speech.service",
        ),
        (
            "speech.yaml",
            lambda raw: raw["speech"].update(speaker_id="invalid"),
            "speech.speaker_id",
        ),
        (
            "memory.yaml",
            lambda raw: raw["memory"]["topic_memory"].update(
                embedding_model="unknown_model"
            ),
            "memory.topic_memory.embedding_model",
        ),
        (
            "memory.yaml",
            lambda raw: raw["memory"]["relationship_memory"].update(
                max_entries="invalid"
            ),
            "memory.relationship_memory.max_entries",
        ),
        (
            "services.yaml",
            lambda raw: raw["services"]["openai"].update(
                timeout_seconds="invalid"
            ),
            "services.openai.timeout_seconds",
        ),
        (
            "models.yaml",
            lambda raw: raw["models"]["openai_chat"].update(
                service="unknown_service"
            ),
            "models.openai_chat.service",
        ),
        (
            "models.yaml",
            lambda raw: raw["models"]["openai_embedding"].update(
                dimension="invalid"
            ),
            "models.openai_embedding.dimension",
        ),
    ],
)
def test_split_setting_errors_report_owner_file(
    tmp_path: Path,
    file_name: str,
    change: Callable[[dict[str, Any]], None],
    error_path: str,
) -> None:
    copied_config = tmp_path / "config"
    shutil.copytree(CONFIG_DIRECTORY, copied_config)
    source = copied_config / file_name
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    change(raw)
    source.write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError) as raised:
        load_app_config(copied_config / "index.yaml")
    assert raised.value.path == error_path
    assert raised.value.source_file == str(source.resolve())
