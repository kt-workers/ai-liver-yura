from __future__ import annotations

import copy
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config.errors import ConfigError
from app.config.strict import require_mapping, require_string_value

CONFIG_ENV_ENV = "AI_LIVER_CONFIG_ENV"
_ENVIRONMENT_NAME_PATTERN = re.compile(r"^[a-z0-9_-]+$")


@dataclass(frozen=True, slots=True)
class OverrideOperation:
    path: str
    value: Any


def resolve_config_environment() -> str | None:
    """環境変数から単一の設定環境名を解決する。"""

    configured = os.environ.get(CONFIG_ENV_ENV, "").strip()
    if not configured:
        return None
    if not _ENVIRONMENT_NAME_PATTERN.fullmatch(configured):
        raise ConfigError(
            path=CONFIG_ENV_ENV,
            expected="lowercase environment name using a-z, 0-9, hyphen, or underscore",
            actual=configured,
        )
    return configured


def parse_environment_paths(
    manifest_path: Path,
    value: object | None,
) -> dict[str, Path]:
    """manifestのenvironments mappingをstrictに解決する。"""

    if value is None:
        return {}
    try:
        raw_environments = require_mapping(value, "environments")
    except ConfigError as error:
        raise error.with_source(str(manifest_path)) from error

    environments: dict[str, Path] = {}
    for name, raw_path in raw_environments.items():
        if not isinstance(name, str) or not _ENVIRONMENT_NAME_PATTERN.fullmatch(name):
            raise ConfigError(
                path=f"environments.{name}",
                expected="lowercase environment name using a-z, 0-9, hyphen, or underscore",
                actual=name,
                source_file=str(manifest_path),
            )
        try:
            configured_path = require_string_value(raw_path, f"environments.{name}")
        except ConfigError as error:
            raise error.with_source(str(manifest_path)) from error
        target = Path(configured_path).expanduser()
        if not target.is_absolute():
            target = manifest_path.parent / target
        environments[name] = target.resolve()
    return environments


def resolve_environment_file(
    manifest_path: Path,
    environments: dict[str, Path],
    selected_environment: str | None,
) -> Path | None:
    """選択環境に対応するoverride fileを検証して返す。"""

    if selected_environment is None:
        return None
    target = environments.get(selected_environment)
    if target is None:
        raise ConfigError(
            path=CONFIG_ENV_ENV,
            expected="environment registered in manifest environments",
            actual=selected_environment,
            source_file=str(manifest_path),
        )
    if not target.exists():
        raise ConfigError(
            path=f"environments.{selected_environment}",
            expected="existing environment override file",
            actual="missing",
            source_file=str(target),
        )
    if not target.is_file():
        raise ConfigError(
            path=f"environments.{selected_environment}",
            expected="regular environment override file",
            actual="directory",
            source_file=str(target),
        )
    return target


def reject_legacy_environment(root_path: Path, selected_environment: str | None) -> None:
    """legacy単一設定とenvironment overrideの暗黙併用を拒否する。"""

    if selected_environment is None:
        return
    raise ConfigError(
        path=CONFIG_ENV_ENV,
        expected="manifest configuration entry when environment override is selected",
        actual=f"legacy configuration file: {root_path}",
        source_file=str(root_path),
    )


def parse_override_operations(
    environment_path: Path,
    raw_environment: object,
) -> tuple[OverrideOperation, ...]:
    """environment fileをstrictに解析してoverride操作列へ変換する。"""

    try:
        root = require_mapping(raw_environment, "<root>")
    except ConfigError as error:
        raise error.with_source(str(environment_path)) from error

    extra_root_keys = set(root) - {"overrides"}
    if extra_root_keys:
        key = sorted(extra_root_keys)[0]
        raise ConfigError(
            path=key,
            expected="environment file containing only overrides",
            actual="unknown top-level key",
            source_file=str(environment_path),
        )
    if "overrides" not in root:
        raise ConfigError(
            path="overrides",
            expected="list of override operations",
            actual="missing",
            source_file=str(environment_path),
        )

    raw_operations = root["overrides"]
    if not isinstance(raw_operations, list):
        raise ConfigError(
            path="overrides",
            expected="list",
            actual=type(raw_operations).__name__,
            source_file=str(environment_path),
        )

    operations: list[OverrideOperation] = []
    seen_paths: set[str] = set()
    for index, raw_operation in enumerate(raw_operations):
        operation_path = f"overrides.{index}"
        try:
            operation = require_mapping(raw_operation, operation_path)
        except ConfigError as error:
            raise error.with_source(str(environment_path)) from error

        extra_fields = set(operation) - {"path", "value"}
        if extra_fields:
            field = sorted(extra_fields)[0]
            raise ConfigError(
                path=f"{operation_path}.{field}",
                expected="override operation containing only path and value",
                actual="unknown field",
                source_file=str(environment_path),
            )
        if "path" not in operation:
            raise ConfigError(
                path=f"{operation_path}.path",
                expected="non-blank dot path",
                actual="missing",
                source_file=str(environment_path),
            )
        if "value" not in operation:
            raise ConfigError(
                path=f"{operation_path}.value",
                expected="replacement value",
                actual="missing",
                source_file=str(environment_path),
            )
        try:
            yaml_path = require_string_value(operation["path"], f"{operation_path}.path")
        except ConfigError as error:
            raise error.with_source(str(environment_path)) from error
        if any(not segment for segment in yaml_path.split(".")):
            raise ConfigError(
                path=f"{operation_path}.path",
                expected="dot path without empty segments",
                actual=yaml_path,
                source_file=str(environment_path),
            )
        if yaml_path in seen_paths:
            raise ConfigError(
                path=f"{operation_path}.path",
                expected="unique override path",
                actual=f"duplicate path {yaml_path}",
                source_file=str(environment_path),
            )
        seen_paths.add(yaml_path)
        operations.append(OverrideOperation(path=yaml_path, value=operation["value"]))

    return tuple(operations)


def apply_override_operations(
    base_values: dict[str, Any],
    operations: tuple[OverrideOperation, ...],
    environment_path: Path,
) -> dict[str, Any]:
    """全操作を検証後、既存leaf値だけを同型値で置換する。"""

    targets: list[tuple[list[str], Any]] = []
    for operation in operations:
        segments = operation.path.split(".")
        current: Any = base_values
        for segment in segments[:-1]:
            if not isinstance(current, dict) or segment not in current:
                raise ConfigError(
                    path=operation.path,
                    expected="existing leaf path",
                    actual="missing path",
                    source_file=str(environment_path),
                )
            current = current[segment]
        leaf = segments[-1]
        if not isinstance(current, dict) or leaf not in current:
            raise ConfigError(
                path=operation.path,
                expected="existing leaf path",
                actual="missing path",
                source_file=str(environment_path),
            )

        existing = current[leaf]
        replacement = operation.value
        if isinstance(existing, (dict, list)):
            raise ConfigError(
                path=operation.path,
                expected="scalar leaf value",
                actual=type(existing).__name__,
                source_file=str(environment_path),
            )
        if isinstance(replacement, (dict, list)):
            raise ConfigError(
                path=operation.path,
                expected=f"same scalar type as {type(existing).__name__}",
                actual=type(replacement).__name__,
                source_file=str(environment_path),
            )
        if not _same_scalar_type(existing, replacement):
            raise ConfigError(
                path=operation.path,
                expected=f"same type as {type(existing).__name__}",
                actual=type(replacement).__name__,
                source_file=str(environment_path),
            )
        targets.append((segments, replacement))

    result = copy.deepcopy(base_values)
    for segments, replacement in targets:
        current = result
        for segment in segments[:-1]:
            current = current[segment]
        current[segments[-1]] = replacement
    return result


def _same_scalar_type(existing: Any, replacement: Any) -> bool:
    if existing is None or replacement is None:
        return existing is None and replacement is None
    if isinstance(existing, bool) or isinstance(replacement, bool):
        return isinstance(existing, bool) and isinstance(replacement, bool)
    if isinstance(existing, int):
        return isinstance(replacement, int) and not isinstance(replacement, bool)
    if isinstance(existing, float):
        return isinstance(replacement, (int, float)) and not isinstance(replacement, bool)
    return type(existing) is type(replacement)
