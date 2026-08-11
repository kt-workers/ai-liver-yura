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
    """期待値を見ずにCharacter speechから観測したproposition意味。"""

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
