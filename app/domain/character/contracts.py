from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.domain.contracts.common import require_identifier, require_revision


class CharacterCertainty(str, Enum):
    CONFIRMED = "confirmed"
    CANDIDATE = "candidate"
    UNKNOWN = "unknown"
    NOT_CONFIGURED = "not_configured"


class RuntimeAvailability(str, Enum):
    CONFIRMED = "confirmed"
    UNRESOLVED = "unresolved"
    NOT_CONFIGURED = "not_configured"


@dataclass(frozen=True, slots=True)
class CharacterAuthority:
    bible_path: str
    owner_issue: int

    def __post_init__(self) -> None:
        require_identifier(self.bible_path, "bible_path")
        if type(self.owner_issue) is not int or self.owner_issue < 1:
            raise ValueError("owner_issue は正の整数でなければなりません")


@dataclass(frozen=True, slots=True)
class CharacterFacet:
    facet_id: str
    certainty: CharacterCertainty
    value: str | None = None
    description: str | None = None
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.facet_id, "facet_id")
        if not isinstance(self.certainty, CharacterCertainty):
            raise ValueError("certainty は CharacterCertainty でなければなりません")
        if self.certainty in (CharacterCertainty.CONFIRMED, CharacterCertainty.CANDIDATE):
            require_identifier(self.value or "", "value")
        elif self.value is not None:
            raise ValueError("unknown/not_configured に value は指定できません")
        if self.description is not None:
            require_identifier(self.description, "description")
        tags = tuple(self.tags)
        if any(not isinstance(tag, str) or not tag.strip() for tag in tags):
            raise ValueError("tags は空でない文字列でなければなりません")
        if len(tags) != len(set(tags)):
            raise ValueError("tags は重複できません")
        object.__setattr__(self, "tags", tags)


def _facets(value: tuple[CharacterFacet, ...], field_name: str) -> tuple[CharacterFacet, ...]:
    result = tuple(value)
    if any(not isinstance(item, CharacterFacet) for item in result):
        raise ValueError(f"{field_name} は CharacterFacet の列でなければなりません")
    identifiers = [item.facet_id for item in result]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError(f"{field_name} の id は一意でなければなりません")
    return result


@dataclass(frozen=True, slots=True)
class CharacterDefinitionDocument:
    schema_version: int
    character_id: str
    definition_revision: int
    authority: CharacterAuthority
    identity: tuple[CharacterFacet, ...] = ()
    dispositions: tuple[CharacterFacet, ...] = ()
    deep_priors: tuple[CharacterFacet, ...] = ()
    values: tuple[CharacterFacet, ...] = ()
    preferences: tuple[CharacterFacet, ...] = ()
    self_model: tuple[CharacterFacet, ...] = ()
    language: tuple[CharacterFacet, ...] = ()
    voice: tuple[CharacterFacet, ...] = ()
    body: tuple[CharacterFacet, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("未対応の schema_version です")
        require_identifier(self.character_id, "character_id")
        require_revision(self.definition_revision, "definition_revision")
        if not isinstance(self.authority, CharacterAuthority):
            raise ValueError("authority は CharacterAuthority でなければなりません")
        for name in (
            "identity",
            "dispositions",
            "deep_priors",
            "values",
            "preferences",
            "self_model",
            "language",
            "voice",
            "body",
        ):
            object.__setattr__(self, name, _facets(getattr(self, name), name))
        all_ids = [
            facet.facet_id
            for name in (
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
            for facet in getattr(self, name)
        ]
        if len(all_ids) != len(set(all_ids)):
            raise ValueError("CharacterDefinition の facet id は文書内で一意でなければなりません")


@dataclass(frozen=True, slots=True)
class RuntimeCharacterFacet:
    facet_id: str
    availability: RuntimeAvailability
    value: str | None = None

    def __post_init__(self) -> None:
        require_identifier(self.facet_id, "facet_id")
        if self.availability is RuntimeAvailability.CONFIRMED:
            require_identifier(self.value or "", "value")
        elif self.value is not None:
            raise ValueError("未解決または未設定の Runtime facet に value は指定できません")


@dataclass(frozen=True, slots=True)
class _ProfileBase:
    character_id: str
    schema_version: int
    definition_revision: int
    facets: tuple[RuntimeCharacterFacet, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.character_id, "character_id")
        if self.schema_version != 1:
            raise ValueError("未対応の schema_version です")
        require_revision(self.definition_revision, "definition_revision")
        facets = tuple(self.facets)
        if any(not isinstance(item, RuntimeCharacterFacet) for item in facets):
            raise ValueError("facets は RuntimeCharacterFacet の列でなければなりません")
        if len({item.facet_id for item in facets}) != len(facets):
            raise ValueError("Runtime facet の id は一意でなければなりません")
        object.__setattr__(self, "facets", facets)


@dataclass(frozen=True, slots=True)
class CharacterLanguageProfile(_ProfileBase):
    pass


@dataclass(frozen=True, slots=True)
class CharacterVoiceStyleProfile(_ProfileBase):
    pass


@dataclass(frozen=True, slots=True)
class CharacterBodyStyleProfile(_ProfileBase):
    pass


@dataclass(frozen=True, slots=True)
class CharacterSelfModelProfile(_ProfileBase):
    pass


@dataclass(frozen=True, slots=True)
class CharacterDispositionProfile(_ProfileBase):
    pass


@dataclass(frozen=True, slots=True)
class CharacterPreferenceValueProfile(_ProfileBase):
    pass


@dataclass(frozen=True, slots=True)
class CharacterProjectionBundle:
    language: CharacterLanguageProfile
    voice: CharacterVoiceStyleProfile
    body: CharacterBodyStyleProfile
    self_model: CharacterSelfModelProfile
    dispositions: CharacterDispositionProfile
    preferences_values: CharacterPreferenceValueProfile

    def __post_init__(self) -> None:
        profiles = (
            self.language,
            self.voice,
            self.body,
            self.self_model,
            self.dispositions,
            self.preferences_values,
        )
        if any(not isinstance(profile, _ProfileBase) for profile in profiles):
            raise ValueError("bundle は Character Profile のみを受け取ります")
        provenance = {(p.character_id, p.schema_version, p.definition_revision) for p in profiles}
        if len(provenance) != 1:
            raise ValueError("bundle 内の Profile provenance は一致しなければなりません")
