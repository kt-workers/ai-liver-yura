from __future__ import annotations

from pathlib import Path

import pytest

from app.config.environment_override import (
    OverrideOperation,
    apply_override_operations,
    parse_override_operations,
)
from app.config.errors import ConfigError


def test_parse_override_operations_accepts_path_and_value(tmp_path: Path) -> None:
    environment_path = tmp_path / "local.yaml"

    operations = parse_override_operations(
        environment_path,
        {
            "overrides": [
                {"path": "app.mode", "value": "console"},
                {"path": "streaming.health_timeout_seconds", "value": 60.0},
            ]
        },
    )

    assert operations == (
        OverrideOperation(path="app.mode", value="console"),
        OverrideOperation(path="streaming.health_timeout_seconds", value=60.0),
    )


def test_empty_override_list_is_allowed(tmp_path: Path) -> None:
    assert parse_override_operations(tmp_path / "local.yaml", {"overrides": []}) == ()


@pytest.mark.parametrize(
    "raw,path",
    [
        ({}, "overrides"),
        ({"overrides": {}, "extra": True}, "extra"),
        ({"overrides": {}}, "overrides"),
        ({"overrides": ["app.mode"]}, "overrides.0"),
        ({"overrides": [{"value": "console"}]}, "overrides.0.path"),
        ({"overrides": [{"path": "app.mode"}]}, "overrides.0.value"),
        (
            {"overrides": [{"path": "app.mode", "value": "console", "merge": True}]},
            "overrides.0.merge",
        ),
    ],
)
def test_invalid_override_structure_is_rejected(
    tmp_path: Path,
    raw: object,
    path: str,
) -> None:
    environment_path = tmp_path / "local.yaml"

    with pytest.raises(ConfigError) as raised:
        parse_override_operations(environment_path, raw)

    assert raised.value.path == path
    assert raised.value.source_file == str(environment_path)


@pytest.mark.parametrize("path", ["", ".app.mode", "app..mode", "app.mode."])
def test_empty_path_segments_are_rejected(tmp_path: Path, path: str) -> None:
    environment_path = tmp_path / "local.yaml"

    with pytest.raises(ConfigError) as raised:
        parse_override_operations(
            environment_path,
            {"overrides": [{"path": path, "value": "console"}]},
        )

    assert raised.value.source_file == str(environment_path)


def test_duplicate_paths_are_rejected(tmp_path: Path) -> None:
    environment_path = tmp_path / "local.yaml"

    with pytest.raises(ConfigError, match="duplicate path app.mode") as raised:
        parse_override_operations(
            environment_path,
            {
                "overrides": [
                    {"path": "app.mode", "value": "console"},
                    {"path": "app.mode", "value": "streaming_demo"},
                ]
            },
        )

    assert raised.value.source_file == str(environment_path)


def test_apply_override_operations_replaces_existing_scalar_leaves(tmp_path: Path) -> None:
    environment_path = tmp_path / "local.yaml"
    base = {
        "app": {"mode": "streaming_demo", "debug": False},
        "streaming": {"health_timeout_seconds": 30.0},
    }

    result = apply_override_operations(
        base,
        (
            OverrideOperation("app.mode", "console"),
            OverrideOperation("app.debug", True),
            OverrideOperation("streaming.health_timeout_seconds", 60),
        ),
        environment_path,
    )

    assert result == {
        "app": {"mode": "console", "debug": True},
        "streaming": {"health_timeout_seconds": 60},
    }
    assert base == {
        "app": {"mode": "streaming_demo", "debug": False},
        "streaming": {"health_timeout_seconds": 30.0},
    }


@pytest.mark.parametrize("path", ["app.unknown", "unknown.mode", "app.mode.value"])
def test_unknown_paths_are_rejected(tmp_path: Path, path: str) -> None:
    environment_path = tmp_path / "local.yaml"

    with pytest.raises(ConfigError) as raised:
        apply_override_operations(
            {"app": {"mode": "console"}},
            (OverrideOperation(path, "value"),),
            environment_path,
        )

    assert raised.value.path == path
    assert raised.value.source_file == str(environment_path)


@pytest.mark.parametrize(
    "base,path,value",
    [
        ({"app": {"settings": {"enabled": True}}}, "app.settings", {}),
        ({"app": {"modes": ["console"]}}, "app.modes", ["streaming_demo"]),
        ({"app": {"mode": "console"}}, "app.mode", {"value": "streaming_demo"}),
        ({"app": {"mode": "console"}}, "app.mode", ["streaming_demo"]),
    ],
)
def test_mapping_and_list_replacement_is_rejected(
    tmp_path: Path,
    base: dict[str, object],
    path: str,
    value: object,
) -> None:
    with pytest.raises(ConfigError) as raised:
        apply_override_operations(
            base,
            (OverrideOperation(path, value),),
            tmp_path / "local.yaml",
        )

    assert raised.value.path == path


@pytest.mark.parametrize(
    "existing,replacement",
    [
        ("console", 1),
        (1, "1"),
        (True, 1),
        (1, True),
        (1.0, "1.0"),
        (None, "value"),
        ("value", None),
    ],
)
def test_scalar_type_changes_are_rejected(
    tmp_path: Path,
    existing: object,
    replacement: object,
) -> None:
    with pytest.raises(ConfigError) as raised:
        apply_override_operations(
            {"app": {"value": existing}},
            (OverrideOperation("app.value", replacement),),
            tmp_path / "local.yaml",
        )

    assert raised.value.path == "app.value"


def test_integer_can_replace_float_without_bool_coercion(tmp_path: Path) -> None:
    result = apply_override_operations(
        {"app": {"ratio": 1.5}},
        (OverrideOperation("app.ratio", 2),),
        tmp_path / "local.yaml",
    )

    assert result["app"]["ratio"] == 2


def test_validation_is_atomic_when_later_operation_fails(tmp_path: Path) -> None:
    base = {"app": {"mode": "streaming_demo", "debug": False}}

    with pytest.raises(ConfigError):
        apply_override_operations(
            base,
            (
                OverrideOperation("app.mode", "console"),
                OverrideOperation("app.unknown", True),
            ),
            tmp_path / "local.yaml",
        )

    assert base == {"app": {"mode": "streaming_demo", "debug": False}}
