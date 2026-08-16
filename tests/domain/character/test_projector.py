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
        deep_priors=(
            CharacterFacet("small_target_affinity", CharacterCertainty.CONFIRMED, "gentle"),
        ),
        formative_history=(
            CharacterFacet("first_success", CharacterCertainty.CONFIRMED, "learned"),
        ),
        beliefs=(
            CharacterFacet(
                "growth_from_failure",
                CharacterCertainty.CONFIRMED,
                "failure teaches",
                basis_refs=("formative_history.first_success",),
            ),
        ),
        values=(CharacterFacet("honesty", CharacterCertainty.CONFIRMED, "truthful"),),
        preferences=(CharacterFacet("tea", CharacterCertainty.UNKNOWN),),
        self_model=(CharacterFacet("virtual_self", CharacterCertainty.CONFIRMED, "AI"),),
        narrative_identity=(
            CharacterFacet("learning_story", CharacterCertainty.CONFIRMED, "continue"),
        ),
        adaptations=(CharacterFacet("failure_coping", CharacterCertainty.CANDIDATE, "reflect"),),
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
    assert result.psychological.deep_priors[0].value == "gentle"
    assert result.psychological.formative_history[0].value == "learned"
    assert result.psychological.beliefs[0].basis_refs == ("formative_history.first_success",)
    assert result.psychological.adaptations[0].availability is RuntimeAvailability.UNRESOLVED


def test_psychological_profile_provides_all_static_layers_and_no_live_state() -> None:
    profile = project_character_definition(_document()).psychological

    assert profile.dispositions[0].availability is RuntimeAvailability.UNRESOLVED
    assert profile.deep_priors[0].availability is RuntimeAvailability.CONFIRMED
    assert profile.formative_history[0].availability is RuntimeAvailability.CONFIRMED
    assert profile.beliefs[0].availability is RuntimeAvailability.CONFIRMED
    assert profile.values[0].availability is RuntimeAvailability.CONFIRMED
    assert profile.self_model[0].availability is RuntimeAvailability.CONFIRMED
    assert profile.narrative_identity[0].availability is RuntimeAvailability.CONFIRMED
    assert profile.adaptations[0].availability is RuntimeAvailability.UNRESOLVED
    assert not hasattr(profile, "emotion")
    assert not hasattr(profile, "goal")
    assert not hasattr(profile, "relationship")


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


@pytest.mark.parametrize(
    "basis_refs",
    [
        ("emotion.current",),
        ("beliefs.self",),
    ],
)
def test_domain_rejects_unknown_and_self_basis_refs(basis_refs: tuple[str, ...]) -> None:
    with pytest.raises(ValueError, match="basis_refs"):
        CharacterDefinitionDocument(
            schema_version=1,
            character_id="generic",
            definition_revision=7,
            authority=CharacterAuthority("docs/character/v2/generic.md", 354),
            beliefs=(
                CharacterFacet(
                    "self", CharacterCertainty.CONFIRMED, "value", basis_refs=basis_refs
                ),
            ),
        )


def test_domain_rejects_cyclic_basis_refs() -> None:
    with pytest.raises(ValueError, match="循環"):
        CharacterDefinitionDocument(
            schema_version=1,
            character_id="generic",
            definition_revision=7,
            authority=CharacterAuthority("docs/character/v2/generic.md", 354),
            beliefs=(
                CharacterFacet(
                    "learning",
                    CharacterCertainty.CONFIRMED,
                    "value",
                    basis_refs=("adaptations.coping",),
                ),
            ),
            adaptations=(
                CharacterFacet(
                    "coping",
                    CharacterCertainty.CONFIRMED,
                    "value",
                    basis_refs=("beliefs.learning",),
                ),
            ),
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
