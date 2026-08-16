# ruff: noqa: E501
from __future__ import annotations

from typing import TypeVar

from app.domain.character.contracts import (
    CharacterBodyStyleProfile,
    CharacterCertainty,
    CharacterDefinitionDocument,
    CharacterDispositionProfile,
    CharacterFacet,
    CharacterLanguageProfile,
    CharacterPreferenceValueProfile,
    CharacterProjectionBundle,
    CharacterSelfModelProfile,
    CharacterVoiceStyleProfile,
    RuntimeAvailability,
    RuntimeCharacterFacet,
    _ProfileBase,
)

ProfileT = TypeVar("ProfileT", bound=_ProfileBase)


def _project_facets(facets: tuple[CharacterFacet, ...]) -> tuple[RuntimeCharacterFacet, ...]:
    projected: list[RuntimeCharacterFacet] = []
    for facet in facets:
        if facet.certainty is CharacterCertainty.CONFIRMED:
            projected.append(
                RuntimeCharacterFacet(facet.facet_id, RuntimeAvailability.CONFIRMED, facet.value)
            )
        elif facet.certainty is CharacterCertainty.NOT_CONFIGURED:
            projected.append(
                RuntimeCharacterFacet(facet.facet_id, RuntimeAvailability.NOT_CONFIGURED)
            )
        else:
            projected.append(RuntimeCharacterFacet(facet.facet_id, RuntimeAvailability.UNRESOLVED))
    return tuple(projected)


def _profile(
    document: CharacterDefinitionDocument,
    profile_type: type[ProfileT],
    facets: tuple[CharacterFacet, ...],
) -> ProfileT:
    return profile_type(
        character_id=document.character_id,
        schema_version=document.schema_version,
        definition_revision=document.definition_revision,
        facets=_project_facets(facets),
    )


def project_character_definition(
    document: CharacterDefinitionDocument,
) -> CharacterProjectionBundle:
    """CharacterDefinition を副作用なしに Runtime Profile へ投影する。"""
    if not isinstance(document, CharacterDefinitionDocument):
        raise ValueError("document は CharacterDefinitionDocument でなければなりません")
    return CharacterProjectionBundle(
        language=_profile(document, CharacterLanguageProfile, document.language),
        voice=_profile(document, CharacterVoiceStyleProfile, document.voice),
        body=_profile(document, CharacterBodyStyleProfile, document.body),
        self_model=_profile(
            document, CharacterSelfModelProfile, document.identity + document.self_model
        ),
        dispositions=_profile(
            document, CharacterDispositionProfile, document.dispositions + document.deep_priors
        ),
        preferences_values=_profile(
            document, CharacterPreferenceValueProfile, document.preferences + document.values
        ),
    )
