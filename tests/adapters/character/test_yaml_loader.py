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
            "  - id: voice_style",
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
