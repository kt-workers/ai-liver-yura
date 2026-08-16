# ruff: noqa: E501
from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any

import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode
from yaml.resolver import BaseResolver

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
_ALLOWED_FACET_IDS = {
    "voice": frozenset(
        {
            "baseline_softness",
            "calmness_tendency",
            "emotional_expressiveness_tendency",
            "energy_tendency",
            "pacing_tendency",
        }
    ),
    "body": frozenset(
        {
            "amplitude_tendency",
            "continuity_tendency",
            "gaze_tendency",
            "head_expression_tendency",
            "motion_softness",
            "posture_expression_tendency",
            "spatial_extent_tendency",
            "symmetry_tendency",
        }
    ),
}


class _StrictYamlLoader(yaml.SafeLoader):
    pass


def _construct_mapping_no_duplicates(
    loader: _StrictYamlLoader, node: MappingNode, deep: bool = False
) -> dict[object, object]:
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ConstructorError(
                "mapping",
                node.start_mark,
                f"重複keyを許可しません: {key}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_StrictYamlLoader.add_constructor(
    BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping_no_duplicates
)


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
        allowed_ids = _ALLOWED_FACET_IDS.get(category)
        if allowed_ids is not None and facet_id not in allowed_ids:
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
        parsed = yaml.load(source, Loader=_StrictYamlLoader)
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
