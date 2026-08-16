# ruff: noqa: E501
from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any

import yaml

from app.domain.character.contracts import (
    CharacterAuthority,
    CharacterCertainty,
    CharacterDefinitionDocument,
    CharacterFacet,
)


class CharacterDefinitionLoadFailureCode(str, Enum):
    MALFORMED_YAML = "malformed_yaml"
    INVALID_SCHEMA = "invalid_schema"
    UNSUPPORTED_SCHEMA_VERSION = "unsupported_schema_version"


class CharacterDefinitionLoadError(ValueError):
    def __init__(self, code: CharacterDefinitionLoadFailureCode, message: str) -> None:
        super().__init__(message)
        self.code = code


_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "character_id",
        "definition_revision",
        "authority",
        "identity",
        "dispositions",
        "deep_priors",
        "values",
        "preferences",
        "self_model",
        "language",
        "voice",
        "body",
    }
)
_AUTHORITY_KEYS = frozenset({"bible_path", "owner_issue"})
_FACET_KEYS = frozenset({"id", "state", "value", "description", "tags"})
_KEYED_FACET_KEYS = _FACET_KEYS - {"id"}
_CATEGORIES = (
    "identity",
    "dispositions",
    "deep_priors",
    "values",
    "preferences",
    "self_model",
    "language",
    "voice",
    "body",
)
_FORBIDDEN_FACET_ID_PARTS = {
    "voice": frozenset({"engine", "provider", "speaker", "pitch", "speed", "volume"}),
    "body": frozenset(
        {
            "angle",
            "dof",
            "gesture",
            "home",
            "ik",
            "joint",
            "limit",
            "neutral",
            "pose",
            "preset",
            "skeleton",
            "solver",
        }
    ),
}


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise CharacterDefinitionLoadError(
            CharacterDefinitionLoadFailureCode.INVALID_SCHEMA,
            f"{name} は mapping でなければなりません",
        )
    return value


def _strict_keys(value: Mapping[str, Any], allowed: frozenset[str], name: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise CharacterDefinitionLoadError(
            CharacterDefinitionLoadFailureCode.INVALID_SCHEMA, f"{name} に未定義 key があります"
        )


def _facet(value: Any, category: str, *, keyed_id: str | None = None) -> CharacterFacet:
    raw = _mapping(value, category)
    _strict_keys(raw, _KEYED_FACET_KEYS if keyed_id is not None else _FACET_KEYS, category)
    try:
        facet_id = keyed_id if keyed_id is not None else raw["id"]
        if not isinstance(facet_id, str) or not facet_id.strip():
            raise ValueError("facet id が不正です")
        forbidden_parts = _FORBIDDEN_FACET_ID_PARTS.get(category, frozenset())
        if any(part in facet_id.lower().split("_") for part in forbidden_parts):
            raise ValueError("実行用facetはCharacter Definitionに指定できません")
        certainty = CharacterCertainty(raw["state"])
        tags_raw = raw.get("tags", [])
        if not isinstance(tags_raw, list):
            raise ValueError("tags は配列でなければなりません")
        return CharacterFacet(
            facet_id=facet_id,
            certainty=certainty,
            value=raw.get("value"),
            description=raw.get("description"),
            tags=tuple(tags_raw),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise CharacterDefinitionLoadError(
            CharacterDefinitionLoadFailureCode.INVALID_SCHEMA, f"{category} facet が不正です"
        ) from error


def _category(value: Any, category: str) -> tuple[CharacterFacet, ...]:
    if isinstance(value, Mapping):
        return tuple(_facet(item, category, keyed_id=facet_id) for facet_id, item in value.items())
    if not isinstance(value, list):
        raise ValueError(f"{category} は配列でなければなりません")
    return tuple(_facet(item, category) for item in value)


def load_character_definition_yaml(source: str | bytes) -> CharacterDefinitionDocument:
    try:
        parsed = yaml.safe_load(source)
    except yaml.YAMLError as error:
        raise CharacterDefinitionLoadError(
            CharacterDefinitionLoadFailureCode.MALFORMED_YAML, "YAML 構文が不正です"
        ) from error
    raw = _mapping(parsed, "document")
    _strict_keys(raw, _TOP_LEVEL_KEYS, "document")
    try:
        schema_version = raw["schema_version"]
        if type(schema_version) is not int:
            raise ValueError("schema_version は整数でなければなりません")
        if schema_version != 1:
            raise CharacterDefinitionLoadError(
                CharacterDefinitionLoadFailureCode.UNSUPPORTED_SCHEMA_VERSION,
                "未対応の schema_version です",
            )
        authority_raw = _mapping(raw["authority"], "authority")
        _strict_keys(authority_raw, _AUTHORITY_KEYS, "authority")
        values: dict[str, tuple[CharacterFacet, ...]] = {}
        for category in _CATEGORIES:
            values[category] = _category(raw[category], category)
        return CharacterDefinitionDocument(
            schema_version=schema_version,
            character_id=raw["character_id"],
            definition_revision=raw["definition_revision"],
            authority=CharacterAuthority(
                bible_path=authority_raw["bible_path"], owner_issue=authority_raw["owner_issue"]
            ),
            **values,
        )
    except CharacterDefinitionLoadError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise CharacterDefinitionLoadError(
            CharacterDefinitionLoadFailureCode.INVALID_SCHEMA,
            "CharacterDefinition schema が不正です",
        ) from error
