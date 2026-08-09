from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


_ALLOWED_STATES = frozenset(
    {
        "absent",
        "low",
        "moderate",
        "high",
        "very_high",
        "present",
        "overview",
        "unknown",
    }
)
_ALLOWED_CERTAINTY = frozenset({"low", "medium", "high"})
_ALLOWED_LENGTH = frozenset({"short", "normal", "long"})
_ALLOWED_DISCLOSURE = frozenset({"none", "brief"})


@dataclass(frozen=True, slots=True)
class SemanticTarget:
    """発話が直接扱う意味対象。Raw User Textを保持しない。"""

    type: str
    id: str

    def __post_init__(self) -> None:
        if not self.type.strip() or not self.id.strip():
            raise ValueError("SemanticTargetのtype/idは空にできません。")

    def as_context(self) -> dict[str, str]:
        return {"type": self.type, "id": self.id}


@dataclass(frozen=True, slots=True)
class SemanticProposition:
    """Characterが表現すべき事実意味。日本語表現や内部数値を含めない。"""

    kind: str
    predicate: str
    state: str
    certainty: str = "high"
    concept: str | None = None
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.kind.strip() or not self.predicate.strip():
            raise ValueError("SemanticPropositionのkind/predicateは空にできません。")
        if self.state not in _ALLOWED_STATES:
            raise ValueError("SemanticProposition.stateが不正です。")
        if self.certainty not in _ALLOWED_CERTAINTY:
            raise ValueError("SemanticProposition.certaintyが不正です。")
        if any(not item.strip() for item in self.evidence_refs):
            raise ValueError("evidence_refsに空文字は使用できません。")

    def as_context(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "predicate": self.predicate,
            "state": self.state,
            "certainty": self.certainty,
            "concept": self.concept,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True, slots=True)
class InterpersonalContentContext:
    """Relationshipのうち発言内容の境界に必要な意味化済みfacet。"""

    disclosure_permission: str = "normal"
    boundary_sensitivity: str = "normal"
    social_distance: str = "unspecified"
    current_tension: str = "unspecified"

    def as_context(self) -> dict[str, str]:
        return {
            "disclosure_permission": self.disclosure_permission,
            "boundary_sensitivity": self.boundary_sensitivity,
            "social_distance": self.social_distance,
            "current_tension": self.current_tension,
        }


@dataclass(frozen=True, slots=True)
class SemanticUtterancePlan:
    """Character表現より前に確定する「何を言うか」の型付き正本。"""

    speech_act: str
    target: SemanticTarget | None = None
    propositions: tuple[SemanticProposition, ...] = field(default_factory=tuple)
    required_content: tuple[str, ...] = field(default_factory=tuple)
    optional_content: tuple[str, ...] = field(default_factory=tuple)
    forbidden_additions: tuple[str, ...] = field(default_factory=tuple)
    response_length: str = "normal"
    self_disclosure: str = "none"
    question_budget: int = 0
    new_direction_budget: int = 0
    interpersonal: InterpersonalContentContext = field(
        default_factory=InterpersonalContentContext
    )
    discourse_context: Mapping[str, str] = field(default_factory=dict)
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.speech_act.strip():
            raise ValueError("speech_actは空にできません。")
        if self.response_length not in _ALLOWED_LENGTH:
            raise ValueError("response_lengthが不正です。")
        if self.self_disclosure not in _ALLOWED_DISCLOSURE:
            raise ValueError("self_disclosureが不正です。")
        if self.question_budget not in {0, 1}:
            raise ValueError("question_budgetは0または1にしてください。")
        if self.new_direction_budget not in {0, 1}:
            raise ValueError("new_direction_budgetは0または1にしてください。")
        for values in (
            self.required_content,
            self.optional_content,
            self.forbidden_additions,
            self.reasons,
        ):
            if any(not item.strip() for item in values):
                raise ValueError("SemanticUtterancePlanの文字列配列に空文字は使用できません。")

    def as_context(self) -> dict[str, object]:
        return {
            "speech_act": self.speech_act,
            "target": self.target.as_context() if self.target is not None else None,
            "propositions": [item.as_context() for item in self.propositions],
            "required_content": list(self.required_content),
            "optional_content": list(self.optional_content),
            "forbidden_additions": list(self.forbidden_additions),
            "response_length": self.response_length,
            "self_disclosure": self.self_disclosure,
            "question_budget": self.question_budget,
            "new_direction_budget": self.new_direction_budget,
            "interpersonal": self.interpersonal.as_context(),
            "discourse_context": dict(self.discourse_context),
            "reasons": list(self.reasons),
        }

    @classmethod
    def from_context(cls, value: object) -> SemanticUtterancePlan | None:
        """ResponseContext等の境界を越えたdictを保守的に型付きPlanへ戻す。"""

        if not isinstance(value, Mapping):
            return None
        speech_act = str(value.get("speech_act") or "").strip()
        if not speech_act:
            return None

        target: SemanticTarget | None = None
        target_value = value.get("target")
        if isinstance(target_value, Mapping):
            target_type = str(target_value.get("type") or "").strip()
            target_id = str(target_value.get("id") or "").strip()
            if target_type and target_id:
                target = SemanticTarget(target_type, target_id)

        propositions: list[SemanticProposition] = []
        raw_propositions = value.get("propositions")
        if isinstance(raw_propositions, (list, tuple)):
            for item in raw_propositions:
                if not isinstance(item, Mapping):
                    continue
                kind = str(item.get("kind") or "").strip()
                predicate = str(item.get("predicate") or "").strip()
                state = str(item.get("state") or "unknown").strip()
                certainty = str(item.get("certainty") or "low").strip()
                if not kind or not predicate:
                    continue
                if state not in _ALLOWED_STATES:
                    state = "unknown"
                if certainty not in _ALLOWED_CERTAINTY:
                    certainty = "low"
                concept_value = item.get("concept")
                concept = (
                    str(concept_value).strip()
                    if concept_value is not None and str(concept_value).strip()
                    else None
                )
                evidence_refs = cls._strings(item.get("evidence_refs"))
                propositions.append(
                    SemanticProposition(
                        kind=kind,
                        predicate=predicate,
                        state=state,
                        certainty=certainty,
                        concept=concept,
                        evidence_refs=evidence_refs,
                    )
                )

        interpersonal_value = value.get("interpersonal")
        interpersonal_map = (
            dict(interpersonal_value) if isinstance(interpersonal_value, Mapping) else {}
        )
        interpersonal = InterpersonalContentContext(
            disclosure_permission=cls._semantic_string(
                interpersonal_map.get("disclosure_permission"), "normal"
            ),
            boundary_sensitivity=cls._semantic_string(
                interpersonal_map.get("boundary_sensitivity"), "normal"
            ),
            social_distance=cls._semantic_string(
                interpersonal_map.get("social_distance"), "unspecified"
            ),
            current_tension=cls._semantic_string(
                interpersonal_map.get("current_tension"), "unspecified"
            ),
        )

        discourse_value = value.get("discourse_context")
        discourse = {
            str(key): str(item).strip()
            for key, item in (
                discourse_value.items() if isinstance(discourse_value, Mapping) else ()
            )
            if str(key).strip() and isinstance(item, str) and item.strip()
        }
        response_length = str(value.get("response_length") or "normal")
        if response_length not in _ALLOWED_LENGTH:
            response_length = "normal"
        self_disclosure = str(value.get("self_disclosure") or "none")
        if self_disclosure not in _ALLOWED_DISCLOSURE:
            self_disclosure = "none"

        return cls(
            speech_act=speech_act,
            target=target,
            propositions=tuple(propositions),
            required_content=cls._strings(value.get("required_content")),
            optional_content=cls._strings(value.get("optional_content")),
            forbidden_additions=cls._strings(value.get("forbidden_additions")),
            response_length=response_length,
            self_disclosure=self_disclosure,
            question_budget=1 if value.get("question_budget") == 1 else 0,
            new_direction_budget=1 if value.get("new_direction_budget") == 1 else 0,
            interpersonal=interpersonal,
            discourse_context=discourse,
            reasons=cls._strings(value.get("reasons")),
        )

    @staticmethod
    def _strings(value: object) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            return ()
        return tuple(
            item.strip()
            for item in value
            if isinstance(item, str) and item.strip()
        )

    @staticmethod
    def _semantic_string(value: object, default: str) -> str:
        return str(value).strip() if isinstance(value, str) and value.strip() else default
