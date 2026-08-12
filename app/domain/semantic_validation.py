from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


_OBSERVED_STATES = frozenset(
    {
        "absent",
        "low",
        "moderate",
        "high",
        "very_high",
        "present",
        "overview",
        "unknown",
        "omitted",
    }
)
_OBSERVED_CERTAINTY = frozenset({"low", "medium", "high", "unknown"})

_PREDICATE_RELATIONS = frozenset(
    {"preserved", "omitted", "changed", "unrelated", "ambiguous"}
)
_VALUE_STATUS_RELATIONS = frozenset(
    {
        "preserved",
        "committed_when_unknown",
        "unknown_when_known",
        "omitted",
        "ambiguous",
        "not_applicable",
    }
)
_POLARITY_RELATIONS = frozenset(
    {"preserved", "contradicted", "omitted", "ambiguous", "not_applicable"}
)
_DEGREE_RELATIONS = frozenset(
    {
        "preserved",
        "weaker",
        "stronger",
        "omitted",
        "ambiguous",
        "not_applicable",
    }
)
_CERTAINTY_RELATIONS = frozenset(
    {"preserved", "stronger", "weaker", "ambiguous", "not_applicable"}
)
_CONCEPT_RELATIONS = frozenset(
    {"preserved", "omitted", "changed", "ambiguous", "not_applicable"}
)
_SUMMARY_RELATIONS = frozenset(
    {"preserved", "collapsed", "omitted", "ambiguous", "not_applicable"}
)


@dataclass(frozen=True, slots=True)
class SemanticPlanValidationResult:
    """Character生成前のSemanticUtterancePlan検証結果。"""

    accepted: bool
    reason: str
    differences: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("Semantic validation reasonは空にできません。")
        if any(not item.strip() for item in self.differences):
            raise ValueError("Semantic validation differencesに空文字は使用できません。")

    def as_context(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "reason": self.reason,
            "differences": list(self.differences),
        }


@dataclass(frozen=True, slots=True)
class RealizedSemanticObservation:
    """期待値を見ずにCharacter speechから観測したproposition意味。

    v1 compatibility / diagnostic用。v2 production gateではabsolute state再構成を使わない。
    """

    realization_id: str
    predicate_realized: bool
    observed_state: str
    observed_certainty: str
    predicate_evidence_spans: tuple[str, ...] = field(default_factory=tuple)
    state_evidence_spans: tuple[str, ...] = field(default_factory=tuple)
    certainty_evidence_spans: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.realization_id.strip():
            raise ValueError("realization_idは空にできません。")
        if self.observed_state not in _OBSERVED_STATES:
            raise ValueError("observed_stateが不正です。")
        if self.observed_certainty not in _OBSERVED_CERTAINTY:
            raise ValueError("observed_certaintyが不正です。")
        for spans in (
            self.predicate_evidence_spans,
            self.state_evidence_spans,
            self.certainty_evidence_spans,
        ):
            if any(not item.strip() for item in spans):
                raise ValueError("evidence spanに空文字は使用できません。")

    @classmethod
    def from_mapping(cls, value: object) -> RealizedSemanticObservation | None:
        if not isinstance(value, Mapping):
            return None
        realization_id = value.get("realization_id")
        predicate_realized = value.get("predicate_realized")
        observed_state = value.get("observed_state")
        observed_certainty = value.get("observed_certainty")
        if (
            not isinstance(realization_id, str)
            or not realization_id.strip()
            or not isinstance(predicate_realized, bool)
            or not isinstance(observed_state, str)
            or not isinstance(observed_certainty, str)
        ):
            return None
        span_fields: list[tuple[str, ...]] = []
        for field_name in (
            "predicate_evidence_spans",
            "state_evidence_spans",
            "certainty_evidence_spans",
        ):
            raw = value.get(field_name)
            if not isinstance(raw, list) or any(
                not isinstance(item, str) or not item.strip() for item in raw
            ):
                return None
            span_fields.append(tuple(item.strip() for item in raw))
        try:
            return cls(
                realization_id=realization_id.strip(),
                predicate_realized=predicate_realized,
                observed_state=observed_state.strip(),
                observed_certainty=observed_certainty.strip(),
                predicate_evidence_spans=span_fields[0],
                state_evidence_spans=span_fields[1],
                certainty_evidence_spans=span_fields[2],
            )
        except ValueError:
            return None


@dataclass(frozen=True, slots=True)
class PropositionSemanticVerification:
    """Planに対するCharacter speechの相対的意味関係。absolute stateを再構成しない。"""

    proposition_id: str
    realized: bool
    predicate_relation: str
    value_status_relation: str
    polarity_relation: str
    degree_relation: str
    certainty_relation: str
    concept_relation: str
    summary_relation: str
    evidence_spans: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        proposition_id = self.proposition_id.strip()
        if not proposition_id:
            raise ValueError("PropositionSemanticVerification.proposition_idは空にできません。")
        relation_sets = (
            (self.predicate_relation, _PREDICATE_RELATIONS, "predicate_relation"),
            (self.value_status_relation, _VALUE_STATUS_RELATIONS, "value_status_relation"),
            (self.polarity_relation, _POLARITY_RELATIONS, "polarity_relation"),
            (self.degree_relation, _DEGREE_RELATIONS, "degree_relation"),
            (self.certainty_relation, _CERTAINTY_RELATIONS, "certainty_relation"),
            (self.concept_relation, _CONCEPT_RELATIONS, "concept_relation"),
            (self.summary_relation, _SUMMARY_RELATIONS, "summary_relation"),
        )
        for relation, allowed, field_name in relation_sets:
            if relation not in allowed:
                raise ValueError(f"{field_name}が不正です。")
        if len(self.evidence_spans) > 12:
            raise ValueError("verification evidence_spansは12件以下にしてください。")
        normalized_spans: list[str] = []
        for span in self.evidence_spans:
            normalized = span.strip()
            if not normalized:
                raise ValueError("verification evidence_spansに空文字は使用できません。")
            if normalized not in normalized_spans:
                normalized_spans.append(normalized)
        object.__setattr__(self, "proposition_id", proposition_id)
        object.__setattr__(self, "evidence_spans", tuple(normalized_spans))

    def as_context(self) -> dict[str, object]:
        return {
            "proposition_id": self.proposition_id,
            "realized": self.realized,
            "predicate_relation": self.predicate_relation,
            "value_status_relation": self.value_status_relation,
            "polarity_relation": self.polarity_relation,
            "degree_relation": self.degree_relation,
            "certainty_relation": self.certainty_relation,
            "concept_relation": self.concept_relation,
            "summary_relation": self.summary_relation,
            "evidence_spans": list(self.evidence_spans),
        }

    @classmethod
    def from_mapping(cls, value: object) -> "PropositionSemanticVerification" | None:
        if not isinstance(value, Mapping):
            return None
        proposition_id = value.get("proposition_id")
        realized = value.get("realized")
        relation_fields = (
            "predicate_relation",
            "value_status_relation",
            "polarity_relation",
            "degree_relation",
            "certainty_relation",
            "concept_relation",
            "summary_relation",
        )
        if (
            not isinstance(proposition_id, str)
            or not proposition_id.strip()
            or not isinstance(realized, bool)
            or any(not isinstance(value.get(field_name), str) for field_name in relation_fields)
        ):
            return None
        raw_spans = value.get("evidence_spans")
        if not isinstance(raw_spans, list) or any(
            not isinstance(span, str) or not span.strip() for span in raw_spans
        ):
            return None
        try:
            return cls(
                proposition_id=proposition_id,
                realized=realized,
                predicate_relation=str(value["predicate_relation"]),
                value_status_relation=str(value["value_status_relation"]),
                polarity_relation=str(value["polarity_relation"]),
                degree_relation=str(value["degree_relation"]),
                certainty_relation=str(value["certainty_relation"]),
                concept_relation=str(value["concept_relation"]),
                summary_relation=str(value["summary_relation"]),
                evidence_spans=tuple(raw_spans),
            )
        except ValueError:
            return None


@dataclass(frozen=True, slots=True)
class CharacterSemanticVerification:
    """CharacterSemanticVerifierのtyped output。acceptedはLLMに持たせない。"""

    propositions: tuple[PropositionSemanticVerification, ...]
    required_content_preserved: bool
    forbidden_additions_absent: bool
    unsupported_new_fact_absent: bool
    existence_boundary_preserved: bool
    budget_preserved: bool
    global_evidence_spans: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        ids = [item.proposition_id for item in self.propositions]
        if len(ids) != len(set(ids)):
            raise ValueError("CharacterSemanticVerification proposition_idが重複しています。")
        if len(self.global_evidence_spans) > 24:
            raise ValueError("global_evidence_spansは24件以下にしてください。")
        if any(not item.strip() for item in self.global_evidence_spans):
            raise ValueError("global_evidence_spansに空文字は使用できません。")

    def as_context(self) -> dict[str, object]:
        return {
            "propositions": [item.as_context() for item in self.propositions],
            "required_content_preserved": self.required_content_preserved,
            "forbidden_additions_absent": self.forbidden_additions_absent,
            "unsupported_new_fact_absent": self.unsupported_new_fact_absent,
            "existence_boundary_preserved": self.existence_boundary_preserved,
            "budget_preserved": self.budget_preserved,
            "global_evidence_spans": list(self.global_evidence_spans),
        }

    @classmethod
    def from_mapping(cls, value: object) -> "CharacterSemanticVerification" | None:
        if not isinstance(value, Mapping):
            return None
        bool_fields = (
            "required_content_preserved",
            "forbidden_additions_absent",
            "unsupported_new_fact_absent",
            "existence_boundary_preserved",
            "budget_preserved",
        )
        if any(not isinstance(value.get(field_name), bool) for field_name in bool_fields):
            return None
        raw_propositions = value.get("propositions")
        if not isinstance(raw_propositions, list):
            return None
        propositions: list[PropositionSemanticVerification] = []
        for raw in raw_propositions:
            parsed = PropositionSemanticVerification.from_mapping(raw)
            if parsed is None:
                return None
            propositions.append(parsed)
        raw_global_spans = value.get("global_evidence_spans")
        if not isinstance(raw_global_spans, list) or any(
            not isinstance(span, str) or not span.strip() for span in raw_global_spans
        ):
            return None
        try:
            return cls(
                propositions=tuple(propositions),
                required_content_preserved=bool(value["required_content_preserved"]),
                forbidden_additions_absent=bool(value["forbidden_additions_absent"]),
                unsupported_new_fact_absent=bool(value["unsupported_new_fact_absent"]),
                existence_boundary_preserved=bool(value["existence_boundary_preserved"]),
                budget_preserved=bool(value["budget_preserved"]),
                global_evidence_spans=tuple(raw_global_spans),
            )
        except ValueError:
            return None
