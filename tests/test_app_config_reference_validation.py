from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.config.app_config import CONFIG_PATH, load_app_config
from app.config.errors import ConfigError


def _load_changed(
    tmp_path: Path, change: Callable[[dict[str, Any]], None]
) -> object:
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    changed = deepcopy(raw)
    change(changed)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(changed, allow_unicode=True), encoding="utf-8")
    return load_app_config(path)


@pytest.mark.parametrize(
    ("change", "path"),
    [
        (
            lambda raw: raw["models"]["openai_chat"].update(service="missing"),
            r"models\.openai_chat\.service",
        ),
        (
            lambda raw: raw["response_generator"].update(model="missing"),
            r"response_generator\.model",
        ),
        (
            lambda raw: raw["llm_roles"]["character"].update(model="missing"),
            r"llm_roles\.character\.model",
        ),
        (
            lambda raw: raw["topic_classifier"].update(model="missing"),
            r"topic_classifier\.model",
        ),
        (
            lambda raw: raw["memory"]["topic_memory"].update(embedding_model="missing"),
            r"memory\.topic_memory\.embedding_model",
        ),
        (
            lambda raw: raw["memory"]["topic_memory"]["summary"].update(model="missing"),
            r"memory\.topic_memory\.summary\.model",
        ),
        (
            lambda raw: raw["speech"].update(service="missing"),
            r"speech\.service",
        ),
        (
            lambda raw: raw["memory"]["topic_memory"].update(
                database_service="missing"
            ),
            r"memory\.topic_memory\.database_service",
        ),
        (
            lambda raw: raw["models"]["openai_embedding"].update(dimension=0),
            r"models\.openai_embedding\.dimension",
        ),
    ],
)
def test_reference_graph_rejects_broken_references(
    tmp_path: Path,
    change: Callable[[dict[str, Any]], None],
    path: str,
) -> None:
    with pytest.raises(ConfigError, match=path):
        _load_changed(tmp_path, change)


def test_disabled_features_do_not_require_their_references(tmp_path: Path) -> None:
    def change(raw: dict[str, Any]) -> None:
        raw["speech"].update(enabled=False, service="missing")
        raw["memory"]["topic_memory"].update(
            enabled=False,
            database_service="missing",
            embedding_model="missing",
        )
        raw["memory"]["topic_memory"]["summary"].update(model="missing")

    config = _load_changed(tmp_path, change)
    assert config.speech.enabled is False
    assert config.memory.topic_memory.enabled is False


def test_config_without_games_or_games_model_loads(tmp_path: Path) -> None:
    def change(raw: dict[str, Any]) -> None:
        raw["plugins"].pop("games", None)
        raw["models"].pop("games_intent", None)

    config = _load_changed(tmp_path, change)
    assert not hasattr(config.plugins, "games")
    assert "games_intent" not in config.models


def test_model_service_type_must_be_ai_compatible(tmp_path: Path) -> None:
    def change(raw: dict[str, Any]) -> None:
        raw["models"]["openai_chat"].update(service="topic_memory_database")

    with pytest.raises(ConfigError, match=r"models\.openai_chat\.service"):
        _load_changed(tmp_path, change)
