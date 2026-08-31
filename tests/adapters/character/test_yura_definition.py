from __future__ import annotations

from pathlib import Path

from app.adapters.character.yaml_loader import load_character_definition_yaml
from app.domain.character.contracts import (
    CharacterCertainty,
    CharacterDefinitionDocument,
    RuntimeAvailability,
)
from app.domain.character.projector import project_character_definition

_ROOT = Path(__file__).resolve().parents[3]
_YURA_DEFINITION = _ROOT / "resources" / "character_definitions" / "v2" / "yura.yaml"
_LEGACY_YURA_DEFINITION = _ROOT / "character_definitions" / "v2" / "yura.yaml"
_DYNAMIC_FACET_IDS = frozenset(
    {
        "emotion",
        "desire",
        "drive",
        "motivation",
        "relationship",
        "goal",
        "commitment",
        "attention",
        "focus",
        "turn",
        "interest",
        "memory",
        "activity",
        "execution",
        "situation",
        "meaning",
    }
)


def _document() -> CharacterDefinitionDocument:
    return load_character_definition_yaml(_YURA_DEFINITION.read_text(encoding="utf-8"))


def test_yura_definition_uses_versioned_runtime_resource_location() -> None:
    assert _YURA_DEFINITION.is_file()
    assert not _LEGACY_YURA_DEFINITION.exists()


def test_yura_definition_strict_loads_with_expected_provenance() -> None:
    document = _document()

    assert document.character_id == "yura"
    assert document.schema_version == 1
    assert document.definition_revision == 1
    assert document.authority.bible_path == "docs/character/v2/yura_character_bible.md"
    assert document.authority.owner_issue == 354


def test_yura_definition_preserves_confirmed_and_unknown_certainty() -> None:
    document = _document()
    identity = {facet.facet_id: facet for facet in document.identity}
    narrative = {facet.facet_id: facet for facet in document.narrative_identity}

    assert identity["display_name"].certainty is CharacterCertainty.CONFIRMED
    assert identity["age_impression"].value == "15〜16歳程度"
    assert identity["exact_age"].certainty is CharacterCertainty.UNKNOWN
    assert identity["exact_age"].value is None
    assert identity["birthday"].certainty is CharacterCertainty.UNKNOWN
    assert narrative["public_lore"].certainty is CharacterCertainty.CONFIRMED
    assert narrative["name_origin"].certainty is CharacterCertainty.UNKNOWN
    assert narrative["deep_sea_origin_detail"].certainty is CharacterCertainty.UNKNOWN


def test_yura_language_voice_and_body_profiles_are_production_ready() -> None:
    bundle = project_character_definition(_document())
    language = {facet.facet_id: facet for facet in bundle.language.facets}
    voice = {facet.facet_id: facet for facet in bundle.voice.facets}
    body = {facet.facet_id: facet for facet in bundle.body.facets}

    assert language["first_person"].availability is RuntimeAvailability.CONFIRMED
    assert language["first_person"].value == "ゆら"
    assert language["register"].value == "乱暴ではない優しいタメ口"
    assert (
        language["response_length_tendency"].value
        == "通常時は短めから中程度のまとまりで、相手が入れる間を残す"
    )
    assert all(facet.availability is RuntimeAvailability.CONFIRMED for facet in voice.values())
    assert voice["baseline_softness"].value == "柔らかく親しみがある"
    assert all(facet.availability is RuntimeAvailability.CONFIRMED for facet in body.values())
    assert body["motion_softness"].value == "柔らかな軌道、timing、余韻を基調とする"


def test_yura_psychological_projection_matches_bible_static_layers() -> None:
    bundle = project_character_definition(_document())
    profile = bundle.psychological

    assert len(profile.dispositions) == 5
    assert len(profile.deep_priors) == 5
    assert len(profile.values) == 5
    assert len(profile.self_model) == 2
    assert len(profile.adaptations) == 5
    assert profile.formative_history == ()
    assert profile.beliefs == ()
    assert all(
        facet.availability is RuntimeAvailability.CONFIRMED
        for facet in (
            *profile.dispositions,
            *profile.deep_priors,
            *profile.values,
            *profile.self_model,
            *profile.adaptations,
        )
    )


def test_yura_definition_has_no_dynamic_state_or_rejected_legacy_preferences() -> None:
    document = _document()
    all_facets = (
        document.identity
        + document.dispositions
        + document.deep_priors
        + document.formative_history
        + document.beliefs
        + document.values
        + document.preferences
        + document.self_model
        + document.narrative_identity
        + document.adaptations
        + document.language
        + document.voice
        + document.body
    )

    for facet in all_facets:
        normalized = facet.facet_id.casefold()
        assert not normalized.startswith("current_")
        assert normalized not in _DYNAMIC_FACET_IDS

    preferences = {facet.facet_id: facet.value for facet in document.preferences}
    assert preferences == {
        "sea_life": "海の生き物",
        "games": "ゲーム",
        "new_technology": "新しい技術",
    }
    source = _YURA_DEFINITION.read_text(encoding="utf-8")
    assert "攻撃的な話題が苦手" not in source
    assert "一方的で長すぎる説明が苦手" not in source
