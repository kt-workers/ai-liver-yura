# ruff: noqa: E501
from __future__ import annotations

import pytest

from app.adapters.character.yaml_loader import (
    CharacterDefinitionLoadError,
    CharacterDefinitionLoadFailureCode,
    load_character_definition_yaml,
)
from app.domain.character.contracts import CharacterCertainty


def _yaml() -> str:
    return "\n".join(
        (
            "schema_version: 1",
            "character_id: generic",
            "definition_revision: 1",
            "authority:",
            "  bible_path: docs/character/v2/generic.md",
            "  owner_issue: 354",
            "identity:",
            "  - id: display_name",
            "    state: confirmed",
            "    value: Generic",
            "dispositions:",
            "  - id: calmness",
            "    state: candidate",
            "    value: calm",
            "deep_priors: []",
            "values: []",
            "preferences:",
            "  - id: tea",
            "    state: unknown",
            "self_model: []",
            "language: []",
            "voice:",
            "  - id: baseline_softness",
            "    state: not_configured",
            "body: []",
            "",
        )
    )


def test_loads_valid_immutable_document() -> None:
    document = load_character_definition_yaml(_yaml())

    assert document.character_id == "generic"
    assert document.dispositions[0].certainty is CharacterCertainty.CANDIDATE


@pytest.mark.parametrize(
    ("source", "code"),
    [
        (_yaml() + "unexpected: value\n", CharacterDefinitionLoadFailureCode.INVALID_SCHEMA),
        (
            _yaml().replace("  owner_issue: 354", "  unknown: value"),
            CharacterDefinitionLoadFailureCode.INVALID_SCHEMA,
        ),
        (
            _yaml().replace("    value: Generic", "    unexpected: value"),
            CharacterDefinitionLoadFailureCode.INVALID_SCHEMA,
        ),
        (
            _yaml().replace("schema_version: 1", "schema_version: 2"),
            CharacterDefinitionLoadFailureCode.UNSUPPORTED_SCHEMA_VERSION,
        ),
        (
            _yaml().replace("schema_version: 1", "schema_version: true"),
            CharacterDefinitionLoadFailureCode.INVALID_SCHEMA,
        ),
        (
            _yaml().replace("schema_version: 1", "schema_version: 1.0"),
            CharacterDefinitionLoadFailureCode.INVALID_SCHEMA,
        ),
        (
            _yaml().replace("value: Generic", "value: ["),
            CharacterDefinitionLoadFailureCode.MALFORMED_YAML,
        ),
        (
            _yaml().replace("    value: Generic\n", ""),
            CharacterDefinitionLoadFailureCode.INVALID_SCHEMA,
        ),
        (
            _yaml().replace("state: confirmed", "state: unknown", 1),
            CharacterDefinitionLoadFailureCode.INVALID_SCHEMA,
        ),
        (
            _yaml().replace("state: confirmed", "state: guessed", 1),
            CharacterDefinitionLoadFailureCode.INVALID_SCHEMA,
        ),
        (
            _yaml().replace(
                "    state: not_configured", "    state: not_configured\n    value: forbidden"
            ),
            CharacterDefinitionLoadFailureCode.INVALID_SCHEMA,
        ),
        (
            _yaml().replace("state: confirmed\n    value: Generic", "state: candidate"),
            CharacterDefinitionLoadFailureCode.INVALID_SCHEMA,
        ),
    ],
)
def test_rejects_invalid_documents(source: str, code: CharacterDefinitionLoadFailureCode) -> None:
    with pytest.raises(CharacterDefinitionLoadError) as error:
        load_character_definition_yaml(source)
    assert error.value.code is code


def test_rejects_duplicate_facet_id() -> None:
    duplicate = _yaml().replace(
        "deep_priors: []",
        "deep_priors:\n  - id: display_name\n    state: confirmed\n    value: Other",
    )
    with pytest.raises(CharacterDefinitionLoadError):
        load_character_definition_yaml(duplicate)


@pytest.mark.parametrize(
    "facet_id",
    ["speaker-id", "speakerId", "provider_pitch", "joint-angles", "pose", "gesture_preset"],
)
def test_rejects_voice_and_body_execution_facets(facet_id: str) -> None:
    if facet_id in {"speaker-id", "speakerId", "provider_pitch"}:
        source = _yaml().replace("  - id: baseline_softness", f"  - id: {facet_id}")
    else:
        source = _yaml().replace(
            "body: []",
            f"body:\n  - id: {facet_id}\n    state: confirmed\n    value: forbidden",
        )
    with pytest.raises(CharacterDefinitionLoadError):
        load_character_definition_yaml(source)


def test_accepts_keyed_mapping_facets() -> None:
    source = _yaml().replace(
        "language: []",
        "language:\n  first_person:\n    state: confirmed\n    value: 私",
    )
    document = load_character_definition_yaml(source)
    assert document.language[0].facet_id == "first_person"
    assert document.language[0].value == "私"


def test_accepts_allowed_voice_and_body_facets() -> None:
    source = _yaml().replace(
        "body: []",
        "body:\n  - id: motion_softness\n    state: confirmed\n    value: smooth",
    )
    document = load_character_definition_yaml(source)
    assert document.voice[0].facet_id == "baseline_softness"
    assert document.body[0].facet_id == "motion_softness"


def test_rejects_duplicate_yaml_mapping_keys() -> None:
    source = _yaml().replace(
        "language: []",
        "language:\n  first_person:\n    state: confirmed\n    value: 私\n  first_person:\n    state: confirmed\n    value: 僕",
    )
    with pytest.raises(CharacterDefinitionLoadError) as error:
        load_character_definition_yaml(source)
    assert error.value.code is CharacterDefinitionLoadFailureCode.MALFORMED_YAML


def test_rejects_unhashable_yaml_mapping_key_as_typed_failure() -> None:
    with pytest.raises(CharacterDefinitionLoadError) as error:
        load_character_definition_yaml("? [invalid]\n: value\n")
    assert error.value.code is CharacterDefinitionLoadFailureCode.MALFORMED_YAML
