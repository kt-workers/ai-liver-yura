from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Any, TypeVar

from app.config.errors import ConfigError

ValueT = TypeVar("ValueT")


def require_mapping(value: object, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(path=path, expected="object", actual=type(value).__name__)
    for key in value:
        if not isinstance(key, str) or not key.strip():
            raise ConfigError(
                path=path,
                expected="object with non-empty string keys",
                actual=type(key).__name__,
            )
    return value


def optional_mapping(config: Mapping[str, Any], key: str, path: str) -> dict[str, Any]:
    value = config.get(key)
    if value is None:
        return {}
    return require_mapping(value, f"{path}.{key}")


def reject_unknown_keys(
    config: Mapping[str, Any],
    allowed: Iterable[str],
    path: str,
) -> None:
    unknown = set(config) - set(allowed)
    if unknown:
        key = sorted(unknown)[0]
        raise ConfigError(
            path=f"{path}.{key}" if path else key,
            expected="known setting key",
            actual="unknown key",
        )


def required_value(config: Mapping[str, Any], key: str, path: str) -> Any:
    if key not in config:
        raise ConfigError(
            path=f"{path}.{key}" if path else key,
            expected="required value",
            actual="missing",
        )
    return config[key]


def require_string_value(value: object, path: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(path=path, expected="string", actual=type(value).__name__)
    if not value.strip():
        raise ConfigError(path=path, expected="non-blank string", actual="blank string")
    return value


def require_string(config: Mapping[str, Any], key: str, path: str) -> str:
    return require_string_value(required_value(config, key, path), f"{path}.{key}")


def optional_string(config: Mapping[str, Any], key: str, path: str) -> str | None:
    value = config.get(key)
    if value is None:
        return None
    return require_string_value(value, f"{path}.{key}")


def require_bool_value(value: object, path: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(path=path, expected="boolean", actual=type(value).__name__)
    return value


def require_bool(config: Mapping[str, Any], key: str, path: str) -> bool:
    return require_bool_value(required_value(config, key, path), f"{path}.{key}")


def optional_bool(
    config: Mapping[str, Any],
    key: str,
    path: str,
    *,
    default: bool,
) -> bool:
    if key not in config:
        return default
    return require_bool_value(config[key], f"{path}.{key}")


def require_int_value(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(path=path, expected="integer", actual=type(value).__name__)
    return value


def require_int(config: Mapping[str, Any], key: str, path: str) -> int:
    return require_int_value(required_value(config, key, path), f"{path}.{key}")


def optional_int(
    config: Mapping[str, Any],
    key: str,
    path: str,
    *,
    default: int | None = None,
) -> int | None:
    value = config.get(key)
    if value is None:
        return default
    return require_int_value(value, f"{path}.{key}")


def require_number_value(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(path=path, expected="number", actual=type(value).__name__)
    return float(value)


def require_number(config: Mapping[str, Any], key: str, path: str) -> float:
    return require_number_value(required_value(config, key, path), f"{path}.{key}")


def optional_number(
    config: Mapping[str, Any],
    key: str,
    path: str,
    *,
    default: float | None = None,
) -> float | None:
    value = config.get(key)
    if value is None:
        return default
    return require_number_value(value, f"{path}.{key}")


def require_string_sequence(
    config: Mapping[str, Any],
    key: str,
    path: str,
    *,
    allow_empty: bool = True,
) -> tuple[str, ...]:
    value = required_value(config, key, path)
    return string_sequence_value(value, f"{path}.{key}", allow_empty=allow_empty)


def string_sequence_value(
    value: object,
    path: str,
    *,
    allow_empty: bool = True,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ConfigError(path=path, expected="list", actual=type(value).__name__)
    if not allow_empty and not value:
        raise ConfigError(path=path, expected="non-empty list", actual="empty list")
    parsed: list[str] = []
    for index, item in enumerate(value):
        parsed.append(require_string_value(item, f"{path}[{index}]"))
    return tuple(parsed)


def immutable_mapping(values: Mapping[str, ValueT]) -> Mapping[str, ValueT]:
    return MappingProxyType(dict(values))
