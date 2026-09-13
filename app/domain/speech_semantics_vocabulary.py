"""#362の発話意味の型と不変な語彙。製品方針の実値は登録しない。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from json import dumps

from app.domain.brain_operational_bounds import BrainOperationalBoundsPolicy
from app.domain.contracts.common import (
    JsonValue,
    freeze_json,
    require_identifier,
    require_revision,
    thaw_json,
)
from app.domain.contracts.finalization import AuthorityGenerationToken


class SpeechSemanticFactKind(str, Enum):
    GENERAL = "general"
    EXECUTION = "execution"
    RELATIONSHIP = "relationship"
    DISCOURSE = "discourse"
    SELF = "self"


class SemanticClaimKind(str, Enum):
    GENERAL = "general"
    EXECUTION_STATUS = "execution_status"


class SpeechPropositionDisposition(str, Enum):
    REQUIRED = "required"
    OPTIONAL = "optional"
    FORBIDDEN = "forbidden"


class SemanticPolarity(str, Enum):
    AFFIRM = "affirm"
    NEGATE = "negate"
    UNKNOWN = "unknown"


class SemanticCertainty(str, Enum):
    CERTAIN = "certain"
    LIKELY = "likely"
    UNCERTAIN = "uncertain"
    UNKNOWN = "unknown"


class SelfDisclosurePolicy(str, Enum):
    FORBIDDEN = "forbidden"
    FACT_GROUNDED = "fact_grounded"
    ALLOWED = "allowed"


class SpeechTruthRule(str, Enum):
    REQUIRE_MATCH = "require_match"
    PRESERVE_UNKNOWN = "preserve_unknown"
    FORBID_COMPLETION_CLAIM = "forbid_completion_claim"


class SpeechSemanticContextFailureCode(str, Enum):
    SOURCE_NOT_FOUND = "SOURCE_NOT_FOUND"
    SOURCE_OWNER_MISMATCH = "SOURCE_OWNER_MISMATCH"
    SOURCE_KIND_MISMATCH = "SOURCE_KIND_MISMATCH"
    SOURCE_IDENTITY_MISMATCH = "SOURCE_IDENTITY_MISMATCH"
    SOURCE_REVISION_MISMATCH = "SOURCE_REVISION_MISMATCH"
    UNSUPPORTED_SOURCE_CONTRACT = "UNSUPPORTED_SOURCE_CONTRACT"
    UNSUPPORTED_PROJECTION = "UNSUPPORTED_PROJECTION"
    TRUTH_RULE_UNRESOLVED = "TRUTH_RULE_UNRESOLVED"
    SEMANTIC_POLICY_UNAVAILABLE = "SEMANTIC_POLICY_UNAVAILABLE"
    SEMANTIC_POLICY_STALE = "SEMANTIC_POLICY_STALE"
    PROJECTION_POLICY_STALE = "PROJECTION_POLICY_STALE"
    CONTEXT_STALE = "CONTEXT_STALE"
    CONTEXT_TOO_LARGE = "CONTEXT_TOO_LARGE"


class SpeechSemanticContextError(ValueError):
    def __init__(self, code: SpeechSemanticContextFailureCode) -> None:
        self.code = code
        super().__init__(f"発話意味文脈を構築できません: {code.value}")


def canonical_size(value: JsonValue) -> int:
    return len(
        dumps(
            thaw_json(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )


class CommunicativeActKind(str, Enum):
    GREETING = "greeting"
    ACKNOWLEDGEMENT = "acknowledgement"
    GRATITUDE = "gratitude"
    APOLOGY = "apology"
    REQUEST = "request"
    COMMITMENT = "commitment"
    CONSENT = "consent"
    REFUSAL = "refusal"
    FAREWELL = "farewell"


class SpeechSourceContractKind(str, Enum):
    GOAL = "goal_state"
    COMMITMENT = "commitment_state"
    EXECUTION = "activity_execution_record"
    MEMORY = "memory_record"
    ATTENTION = "attention_focus_view"
    TRUTH_CONSTRAINT = "speech_truth_constraint"


class CommunicativeTargetMode(str, Enum):
    NONE = "none"
    REQUIRED = "required"


@dataclass(frozen=True, slots=True)
class CommunicativeTargetRequirement:
    mode: CommunicativeTargetMode
    source_contracts: tuple[SpeechSourceContractKind, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.mode, CommunicativeTargetMode)
            or type(self.source_contracts) is not tuple
            or any(not isinstance(x, SpeechSourceContractKind) for x in self.source_contracts)
            or len(set(self.source_contracts)) != len(self.source_contracts)
        ):
            raise ValueError("対象要件の型が不正です")
        if (self.mode is CommunicativeTargetMode.NONE) != (len(self.source_contracts) == 0):
            raise ValueError("対象要件と許容契約が一致しません")

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode.value,
            "source_contracts": [x.value for x in self.source_contracts],
        }


class CommunicativeSubjectBinding(str, Enum):
    LITERAL = "literal"
    TARGET = "target"
    EVIDENCE = "evidence"


@dataclass(frozen=True, slots=True)
class CommunicativeEvidenceRequirement:
    source_contracts: tuple[SpeechSourceContractKind, ...]
    minimum_count: int

    def __post_init__(self) -> None:
        if (
            type(self.source_contracts) is not tuple
            or any(not isinstance(x, SpeechSourceContractKind) for x in self.source_contracts)
            or len(set(self.source_contracts)) != len(self.source_contracts)
            or type(self.minimum_count) is not int
            or self.minimum_count < 0
        ):
            raise ValueError("発話行為の根拠要件が不正です")

    def to_dict(self) -> dict[str, object]:
        return {
            "source_contracts": [x.value for x in self.source_contracts],
            "minimum_count": self.minimum_count,
        }


@dataclass(frozen=True, slots=True)
class CommunicativeSemanticShape:
    subject_ref: str
    predicate: str
    value: JsonValue
    polarity: SemanticPolarity
    certainty: SemanticCertainty
    degree: float | None
    claim_kind: SemanticClaimKind
    subject_binding: CommunicativeSubjectBinding
    evidence_index: int | None

    def __post_init__(self) -> None:
        require_identifier(self.subject_ref, "subject_ref")
        if self.claim_kind is not SemanticClaimKind.GENERAL or not isinstance(
            self.subject_binding, CommunicativeSubjectBinding
        ):
            raise ValueError("発話行為を外部の実行事実として定義できません")
        if self.subject_binding is CommunicativeSubjectBinding.EVIDENCE:
            if type(self.evidence_index) is not int or self.evidence_index < 0:
                raise ValueError("根拠slot番号が必要です")
        elif self.evidence_index is not None:
            raise ValueError("根拠slot番号はEVIDENCEだけに使用できます")
        require_identifier(self.predicate, "predicate")
        if not isinstance(self.polarity, SemanticPolarity) or not isinstance(
            self.certainty, SemanticCertainty
        ):
            raise ValueError("発話行為の意味facetが不正です")
        from math import isfinite

        if self.degree is not None and (
            type(self.degree) not in (float, int)
            or not isfinite(self.degree)
            or not 0 <= self.degree <= 1
        ):
            raise ValueError("発話行為のdegreeが不正です")
        object.__setattr__(self, "value", freeze_json(self.value))

    def to_dict(self) -> dict[str, object]:
        return {
            "subject_ref": self.subject_ref,
            "predicate": self.predicate,
            "value": thaw_json(self.value),
            "polarity": self.polarity.value,
            "certainty": self.certainty.value,
            "degree": self.degree,
            "claim_kind": self.claim_kind.value,
            "subject_binding": self.subject_binding.value,
            "evidence_index": self.evidence_index,
        }


@dataclass(frozen=True, slots=True)
class CommunicativeActDefinition:
    definition_id: str
    definition_revision: int
    act_kind: CommunicativeActKind
    semantic_shape: CommunicativeSemanticShape
    target_requirement: CommunicativeTargetRequirement
    evidence_requirement: CommunicativeEvidenceRequirement

    def __post_init__(self) -> None:
        require_identifier(self.definition_id, "definition_id")
        require_revision(self.definition_revision, "definition_revision")
        for value, expected in (
            (self.act_kind, CommunicativeActKind),
            (self.semantic_shape, CommunicativeSemanticShape),
            (self.target_requirement, CommunicativeTargetRequirement),
            (self.evidence_requirement, CommunicativeEvidenceRequirement),
        ):
            if not isinstance(value, expected):
                raise ValueError("発話行為定義の型が不正です")

    def to_dict(self) -> dict[str, object]:
        return {
            "definition_id": self.definition_id,
            "definition_revision": self.definition_revision,
            "act_kind": self.act_kind.value,
            "semantic_shape": self.semantic_shape.to_dict(),
            "target_requirement": self.target_requirement.to_dict(),
            "evidence_requirement": self.evidence_requirement.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class CommunicativeGoalCatalogView:
    policy_id: str
    policy_revision: int
    definitions: tuple[CommunicativeActDefinition, ...]
    bounds_policy_id: str
    bounds_policy_revision: int
    publication_tokens: tuple[AuthorityGenerationToken, ...] = ()

    def __post_init__(self) -> None:
        for name in ("policy_id", "bounds_policy_id"):
            require_identifier(getattr(self, name), name)
        for name in ("policy_revision", "bounds_policy_revision"):
            require_revision(getattr(self, name), name)
        if (
            type(self.definitions) is not tuple
            or any(not isinstance(x, CommunicativeActDefinition) for x in self.definitions)
            or len({x.definition_id for x in self.definitions}) != len(self.definitions)
        ):
            raise ValueError("発話行為catalogが不正です")

    def to_dict(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "policy_revision": self.policy_revision,
            "definitions": [x.to_dict() for x in self.definitions],
            "bounds_policy_id": self.bounds_policy_id,
            "bounds_policy_revision": self.bounds_policy_revision,
        }

    def validate_bounds(self, bounds: BrainOperationalBoundsPolicy) -> None:
        if (self.bounds_policy_id, self.bounds_policy_revision) != (
            bounds.policy_id,
            bounds.policy_revision,
        ):
            raise SpeechSemanticContextError(SpeechSemanticContextFailureCode.CONTEXT_STALE)
        for definition in self.definitions:
            if definition.evidence_requirement.minimum_count > bounds.speech_semantics.max_facts:
                raise SpeechSemanticContextError(SpeechSemanticContextFailureCode.CONTEXT_TOO_LARGE)
            shape = definition.semantic_shape
            if (
                shape.evidence_index is not None
                and shape.evidence_index >= bounds.speech_semantics.max_facts
            ):
                raise SpeechSemanticContextError(SpeechSemanticContextFailureCode.CONTEXT_TOO_LARGE)
        limits = bounds.communicative_catalog
        from typing import cast

        if (
            len(self.definitions) > limits.max_definitions
            or any(
                canonical_size(cast(JsonValue, d.to_dict())) > limits.max_definition_json_bytes
                for d in self.definitions
            )
            or canonical_size(cast(JsonValue, self.to_dict())) > limits.max_catalog_json_bytes
        ):
            raise SpeechSemanticContextError(SpeechSemanticContextFailureCode.CONTEXT_TOO_LARGE)


@dataclass(frozen=True, slots=True)
class SpeechSemanticMeaningPolicy:
    policy_id: str
    revision: int
    self_disclosure_policy: SelfDisclosurePolicy
    max_question_budget: int
    max_new_direction_budget: int
    communicative_goal_catalog: CommunicativeGoalCatalogView

    def __post_init__(self) -> None:
        require_identifier(self.policy_id, "policy_id")
        require_revision(self.revision, "revision")
        if not isinstance(self.self_disclosure_policy, SelfDisclosurePolicy):
            raise ValueError("自己開示方針の型が不正です")
        for name in ("max_question_budget", "max_new_direction_budget"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError("意味予算は非負整数でなければなりません")
        catalog = self.communicative_goal_catalog
        if not isinstance(catalog, CommunicativeGoalCatalogView):
            raise ValueError("明示したcatalogが必要です")
        if (catalog.policy_id, catalog.policy_revision) != (self.policy_id, self.revision):
            raise ValueError("意味方針とcatalogの世代が一致しません")

    def validate_bounds(self, bounds: BrainOperationalBoundsPolicy) -> None:
        self.communicative_goal_catalog.validate_bounds(bounds)
        limits = bounds.speech_semantics
        if (
            self.max_question_budget > limits.max_question_budget
            or self.max_new_direction_budget > limits.max_new_direction_budget
        ):
            raise SpeechSemanticContextError(SpeechSemanticContextFailureCode.CONTEXT_TOO_LARGE)


def require_meaning_policy(
    value: SpeechSemanticMeaningPolicy | None, bounds: BrainOperationalBoundsPolicy
) -> SpeechSemanticMeaningPolicy:
    if value is None:
        raise SpeechSemanticContextError(
            SpeechSemanticContextFailureCode.SEMANTIC_POLICY_UNAVAILABLE
        )
    if not isinstance(value, SpeechSemanticMeaningPolicy):
        raise ValueError("意味方針の型が不正です")
    value.validate_bounds(bounds)
    return value
