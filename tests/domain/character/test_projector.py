from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.domain.character.contracts import (
    CharacterAuthority,
    CharacterCertainty,
    CharacterDefinitionDocument,
    CharacterFacet,
    RuntimeAvailability,
)
from app.domain.character.projector import project_character_definition


def _document(character_id: str = "generic") -> CharacterDefinitionDocument:
    return CharacterDefinitionDocument(
        schema_version=1,
        character_id=character_id,
        definition_revision=7,
        authority=CharacterAuthority("docs/character/v2/generic.md", 354),
        identity=(CharacterFacet("display_name", CharacterCertainty.CONFIRMED, "Generic"),),
        dispositions=(CharacterFacet("softness", CharacterCertainty.CANDIDATE, "gentle"),),
        values=(CharacterFacet("honesty", CharacterCertainty.CONFIRMED, "truthful"),),
        preferences=(CharacterFacet("tea", CharacterCertainty.UNKNOWN),),
        language=(CharacterFacet("first_person", CharacterCertainty.CONFIRMED, "私"),),
        voice=(CharacterFacet("calmness_tendency", CharacterCertainty.NOT_CONFIGURED),),
        body=(CharacterFacet("motion_softness", CharacterCertainty.CANDIDATE, "soft"),),
    )


def test_projector_preserves_provenance_and_hides_candidate_value() -> None:
    result = project_character_definition(_document())

    assert result.language.character_id == "generic"
    assert result.language.schema_version == 1
    assert result.language.definition_revision == 7
    assert result.language.facets[0].value == "私"
    assert result.dispositions.facets[0].availability is RuntimeAvailability.UNRESOLVED
    assert result.dispositions.facets[0].value is None
    assert result.preferences_values.facets[0].availability is RuntimeAvailability.UNRESOLVED
    assert result.voice.facets[0].availability is RuntimeAvailability.NOT_CONFIGURED
    assert result.body.facets[0].value is None


@pytest.mark.parametrize(
    ("profile", "facet_id"),
    [("voice", "speaker_id"), ("body", "joint_angles")],
)
def test_domain_rejects_execution_facets_before_projection(profile: str, facet_id: str) -> None:
    fields: dict[str, tuple[CharacterFacet, ...]] = {
        "voice": (),
        "body": (),
    }
    fields[profile] = (CharacterFacet(facet_id, CharacterCertainty.CONFIRMED, "forbidden"),)
    with pytest.raises(ValueError, match="未許可"):
        CharacterDefinitionDocument(
            schema_version=1,
            character_id="generic",
            definition_revision=7,
            authority=CharacterAuthority("docs/character/v2/generic.md", 354),
            **fields,
        )


def test_same_projector_handles_alternate_character_and_data_only_change() -> None:
    alternate = _document("alternate")
    changed = CharacterDefinitionDocument(
        schema_version=1,
        character_id="alternate",
        definition_revision=8,
        authority=alternate.authority,
        language=(CharacterFacet("first_person", CharacterCertainty.CONFIRMED, "僕"),),
    )

    assert project_character_definition(alternate).language.character_id == "alternate"
    projected = project_character_definition(changed)
    assert projected.language.definition_revision == 8
    assert projected.language.facets[0].value == "僕"


def test_profile_is_immutable_and_dynamic_contracts_are_absent() -> None:
    result = project_character_definition(_document())

    with pytest.raises(FrozenInstanceError):
        result.language.character_id = "other"  # type: ignore[misc]
    assert not hasattr(result, "emotion")
    assert not hasattr(result.preferences_values, "current_interest")
    assert not hasattr(result.body, "joint_angles")
    assert not hasattr(result.body, "pose")
