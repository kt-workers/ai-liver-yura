from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.config.app_config import CONFIG_PATH, load_app_config
from app.config.errors import ConfigError


def _invalid_config(
    tmp_path: Path, change: Callable[[dict[str, Any]], None]
) -> Path:
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    changed = deepcopy(raw)
    change(changed)
    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump(changed, allow_unicode=True), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("change", "path"),
    [
        (
            lambda raw: raw["speech"].update(enabled="false"),
            r"speech\.enabled",
        ),
        (
            lambda raw: raw["speech"].update(enabled=1),
            r"speech\.enabled",
        ),
        (
            lambda raw: raw["plugins"]["games"]["intent_interpreter"].update(
                max_attempts=2.5
            ),
            r"plugins\.games\.intent_interpreter\.max_attempts",
        ),
        (
            lambda raw: raw["streaming"]["moderation"].update(timeout_seconds="3.0"),
            r"streaming\.moderation\.timeout_seconds",
        ),
        (
            lambda raw: raw["speech"].update(speaker_id=True),
            r"speech\.speaker_id",
        ),
        (
            lambda raw: raw["input_receivers"]["timer"].update(interval_seconds=0),
            r"input_receivers\.timer\.interval_seconds",
        ),
        (
            lambda raw: raw["input_receivers"]["timer"].update(max_events=-1),
            r"input_receivers\.timer\.max_events",
        ),
        (
            lambda raw: raw["character"].update(likes=["海", 123]),
            r"character\.likes\[1\]",
        ),
    ],
)
def test_implicit_scalar_and_list_item_conversions_are_rejected(
    tmp_path: Path,
    change: Callable[[dict[str, Any]], None],
    path: str,
) -> None:
    with pytest.raises(ConfigError, match=path):
        load_app_config(_invalid_config(tmp_path, change))


@pytest.mark.parametrize(
    ("change", "path"),
    [
        (lambda raw: raw.update(appp={}), r"path=appp"),
        (lambda raw: raw["app"].update(mdoe="console"), r"app\.mdoe"),
        (
            lambda raw: raw["services"]["openai"].update(timeot_seconds=3),
            r"services\.openai\.timeot_seconds",
        ),
        (
            lambda raw: raw["models"]["openai_chat"].update(nmae="x"),
            r"models\.openai_chat\.nmae",
        ),
        (
            lambda raw: raw["streaming"]["comment_ranking"].update(
                selection_treshold=0.5
            ),
            r"streaming\.comment_ranking\.selection_treshold",
        ),
    ],
)
def test_unknown_core_keys_include_the_full_yaml_path(
    tmp_path: Path,
    change: Callable[[dict[str, Any]], None],
    path: str,
) -> None:
    with pytest.raises(ConfigError, match=path):
        load_app_config(_invalid_config(tmp_path, change))


def test_yaml_syntax_error_includes_source_path(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("app: [\n", encoding="utf-8")
    with pytest.raises(ConfigError, match=rf"source={path}"):
        load_app_config(path)
