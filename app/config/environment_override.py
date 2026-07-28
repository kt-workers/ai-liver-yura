from __future__ import annotations

import os
import re
from pathlib import Path

from app.config.errors import ConfigError
from app.config.strict import require_mapping, require_string_value

CONFIG_ENV_ENV = "AI_LIVER_CONFIG_ENV"
_ENVIRONMENT_NAME_PATTERN = re.compile(r"^[a-z0-9_-]+$")


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
