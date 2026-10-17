"""S2構成の安全な失敗と厳密な公開値検査を共有する。"""

from __future__ import annotations

import re
from enum import Enum
from typing import NoReturn

import yaml
from yaml.nodes import MappingNode


class S2FailureCode(str, Enum):
    MISSING_SYSTEM_CONFIG = "MISSING_SYSTEM_CONFIG"
    INVALID_SYSTEM_CONFIG = "INVALID_SYSTEM_CONFIG"
    APPRAISAL_CONFIGURATION_FAILED = "APPRAISAL_CONFIGURATION_FAILED"
    EXECUTIVE_CONFIGURATION_FAILED = "EXECUTIVE_CONFIGURATION_FAILED"
    PROVIDER_MAPPING_FAILED = "PROVIDER_MAPPING_FAILED"
    COGNITION_COMPOSITION_FAILED = "COGNITION_COMPOSITION_FAILED"
    ACTIVATION_FAILED = "ACTIVATION_FAILED"
    INITIALIZATION_FAILED = "INITIALIZATION_FAILED"


class S2ConfigurationError(ValueError):
    """入力値や内部例外を公開しないSystem構成失敗。"""

    def __init__(self, code: S2FailureCode) -> None:
        self.code = code
        super().__init__(f"S2構成を使用できません: {code.value}")


def invalid() -> NoReturn:
    raise S2ConfigurationError(S2FailureCode.INVALID_SYSTEM_CONFIG)


def identity(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value) is None:
        invalid()
    return value


def revision(value: object, minimum: int = 1) -> int:
    if type(value) is not int or value < minimum:
        invalid()
    return value


def resource(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or any(
            part in ("", ".", "..") or re.fullmatch(r"[A-Za-z0-9_.-]+", part) is None
            for part in value.split("/")
        )
    ):
        invalid()
    return value


def shape(value: object, fields: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != set(fields.split()):
        invalid()
    return {str(key): item for key, item in value.items()}


class _Loader(yaml.SafeLoader):
    """重複keyを受理しないS2用loader。"""


def _mapping(loader: _Loader, node: MappingNode, deep: bool = False) -> dict[str, object]:
    result: dict[str, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result:
            invalid()
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def parse(source: str | bytes) -> object:
    try:
        result: object = yaml.load(source, Loader=_Loader)
        _acyclic(result, set())
        return result
    except (yaml.YAMLError, TypeError, ValueError, RecursionError, UnicodeError):
        raise S2ConfigurationError(S2FailureCode.INVALID_SYSTEM_CONFIG) from None


def _acyclic(value: object, active: set[int]) -> None:
    if not isinstance(value, (list, dict)):
        return
    if id(value) in active:
        invalid()
    active.add(id(value))
    for child in value.values() if isinstance(value, dict) else value:
        _acyclic(child, active)
    active.remove(id(value))
