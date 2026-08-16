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


_PROFILE_ALLOWED_FACET_IDS = {
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
_CATEGORIES = (
    "identity",
    "dispositions",
    "deep_priors",
    "formative_history",
    "beliefs",
    "values",
    "self_model",
    "narrative_identity",
    "adaptations",
    "preferences",
    "language",
    "voice",
    "body",
)
_PSYCHOLOGICAL_CATEGORIES = (
    "dispositions",
    "deep_priors",
    "formative_history",
    "beliefs",
    "values",
    "self_model",
    "narrative_identity",
    "adaptations",
)
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


def _is_dynamic_facet_id(facet_id: str) -> bool:
    normalized = facet_id.casefold()
    return normalized in _DYNAMIC_FACET_IDS or normalized.startswith("current_")


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
    basis_refs: tuple[str, ...] = ()

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
        basis_refs = tuple(self.basis_refs)
        if any(not isinstance(reference, str) or not reference.strip() for reference in basis_refs):
            raise ValueError("basis_refs は空でない文字列でなければなりません")
        if len(basis_refs) != len(set(basis_refs)):
            raise ValueError("basis_refs は重複できません")
        object.__setattr__(self, "basis_refs", basis_refs)


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
    formative_history: tuple[CharacterFacet, ...] = ()
    beliefs: tuple[CharacterFacet, ...] = ()
    values: tuple[CharacterFacet, ...] = ()
    preferences: tuple[CharacterFacet, ...] = ()
    self_model: tuple[CharacterFacet, ...] = ()
    narrative_identity: tuple[CharacterFacet, ...] = ()
    adaptations: tuple[CharacterFacet, ...] = ()
    language: tuple[CharacterFacet, ...] = ()
    voice: tuple[CharacterFacet, ...] = ()
    body: tuple[CharacterFacet, ...] = ()

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("未対応の schema_version です")
        require_identifier(self.character_id, "character_id")
        require_revision(self.definition_revision, "definition_revision")
        if not isinstance(self.authority, CharacterAuthority):
            raise ValueError("authority は CharacterAuthority でなければなりません")
        for name in _CATEGORIES:
            object.__setattr__(self, name, _facets(getattr(self, name), name))
        for profile_name, allowed_ids in _PROFILE_ALLOWED_FACET_IDS.items():
            if any(facet.facet_id not in allowed_ids for facet in getattr(self, profile_name)):
                raise ValueError(f"{profile_name} に未許可のfacet idがあります")
        if any(
            _is_dynamic_facet_id(facet.facet_id)
            for name in _CATEGORIES
            for facet in getattr(self, name)
        ):
            raise ValueError("CharacterDefinition に動的状態facetは指定できません")
        all_ids = [facet.facet_id for name in _CATEGORIES for facet in getattr(self, name)]
        if len(all_ids) != len(set(all_ids)):
            raise ValueError("CharacterDefinition の facet id は文書内で一意でなければなりません")
        self._validate_basis_refs()

    def _validate_basis_refs(self) -> None:
        facets_by_ref = {
            f"{category}.{facet.facet_id}": facet
            for category in _CATEGORIES
            for facet in getattr(self, category)
        }
        dependencies: dict[str, tuple[str, ...]] = {}
        for category in _CATEGORIES:
            for facet in getattr(self, category):
                reference = f"{category}.{facet.facet_id}"
                if reference in facet.basis_refs:
                    raise ValueError("basis_refs に自己参照は指定できません")
                if any(basis_ref not in facets_by_ref for basis_ref in facet.basis_refs):
                    raise ValueError("basis_refs に未知または動的な参照は指定できません")
                dependencies[reference] = facet.basis_refs

        visiting: set[str] = set()
        visited: set[str] = set()
        for facet_reference in dependencies:
            if facet_reference in visited:
                continue
            stack: list[tuple[str, bool]] = [(facet_reference, False)]
            while stack:
                reference, completed = stack.pop()
                if completed:
                    visiting.remove(reference)
                    visited.add(reference)
                    continue
                if reference in visited:
                    continue
                if reference in visiting:
                    raise ValueError("basis_refs に循環参照は指定できません")
                visiting.add(reference)
                stack.append((reference, True))
                for dependency in reversed(dependencies[reference]):
                    if dependency in visiting:
                        raise ValueError("basis_refs に循環参照は指定できません")
                    if dependency not in visited:
                        stack.append((dependency, False))


@dataclass(frozen=True, slots=True)
class RuntimeCharacterFacet:
    facet_id: str
    availability: RuntimeAvailability
    value: str | None = None
    basis_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.facet_id, "facet_id")
        if self.availability is RuntimeAvailability.CONFIRMED:
            require_identifier(self.value or "", "value")
        elif self.value is not None:
            raise ValueError("未解決または未設定の Runtime facet に value は指定できません")
        basis_refs = tuple(self.basis_refs)
        if any(not isinstance(reference, str) or not reference.strip() for reference in basis_refs):
            raise ValueError("basis_refs は空でない文字列でなければなりません")
        object.__setattr__(self, "basis_refs", basis_refs)


@dataclass(frozen=True, slots=True)
class _ProfileBase:
    character_id: str
    schema_version: int
    definition_revision: int
    facets: tuple[RuntimeCharacterFacet, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.character_id, "character_id")
        if type(self.schema_version) is not int or self.schema_version != 1:
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


def _runtime_facets(
    value: tuple[RuntimeCharacterFacet, ...], field_name: str
) -> tuple[RuntimeCharacterFacet, ...]:
    result = tuple(value)
    if any(not isinstance(item, RuntimeCharacterFacet) for item in result):
        raise ValueError(f"{field_name} は RuntimeCharacterFacet の列でなければなりません")
    if len({item.facet_id for item in result}) != len(result):
        raise ValueError(f"{field_name} の id は一意でなければなりません")
    return result


@dataclass(frozen=True, slots=True)
class CharacterPsychologicalProfile:
    character_id: str
    schema_version: int
    definition_revision: int
    dispositions: tuple[RuntimeCharacterFacet, ...] = ()
    deep_priors: tuple[RuntimeCharacterFacet, ...] = ()
    formative_history: tuple[RuntimeCharacterFacet, ...] = ()
    beliefs: tuple[RuntimeCharacterFacet, ...] = ()
    values: tuple[RuntimeCharacterFacet, ...] = ()
    self_model: tuple[RuntimeCharacterFacet, ...] = ()
    narrative_identity: tuple[RuntimeCharacterFacet, ...] = ()
    adaptations: tuple[RuntimeCharacterFacet, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.character_id, "character_id")
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("未対応の schema_version です")
        require_revision(self.definition_revision, "definition_revision")
        for name in _PSYCHOLOGICAL_CATEGORIES:
            object.__setattr__(self, name, _runtime_facets(getattr(self, name), name))


@dataclass(frozen=True, slots=True)
class CharacterProjectionBundle:
    language: CharacterLanguageProfile
    voice: CharacterVoiceStyleProfile
    body: CharacterBodyStyleProfile
    self_model: CharacterSelfModelProfile
    dispositions: CharacterDispositionProfile
    preferences_values: CharacterPreferenceValueProfile
    psychological: CharacterPsychologicalProfile

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
        if not isinstance(self.psychological, CharacterPsychologicalProfile):
            raise ValueError("bundle は CharacterPsychologicalProfile を必要とします")
        provenance = {
            (p.character_id, p.schema_version, p.definition_revision)
            for p in (*profiles, self.psychological)
        }
        if len(provenance) != 1:
            raise ValueError("bundle 内の Profile provenance は一致しなければなりません")
