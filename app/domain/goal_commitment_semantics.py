"""#366所有の中立なGoal / Commitment意味仕様。Speech型には依存しない。"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import cast

from app.domain.contracts.common import JsonValue, freeze_json, require_identifier, thaw_json


class GoalCommitmentSemanticSubjectKind(str, Enum):
    SELF = "self"
    REFERENCE = "reference"


class GoalCommitmentSemanticPolarity(str, Enum):
    AFFIRM = "affirm"
    NEGATE = "negate"


class GoalCommitmentSemanticModality(str, Enum):
    GOAL = "goal"
    COMMITMENT = "commitment"


class GoalCommitmentSemanticCertainty(str, Enum):
    CERTAIN = "certain"


@dataclass(frozen=True, slots=True)
class GoalCommitmentSemanticSpec:
    semantic_ref: str
    semantic_revision: int
    subject_kind: GoalCommitmentSemanticSubjectKind
    subject_ref: str | None
    predicate: str
    value: JsonValue
    polarity: GoalCommitmentSemanticPolarity
    degree: float | None

    def __post_init__(self) -> None:
        require_identifier(self.semantic_ref, "semantic_ref")
        require_identifier(self.predicate, "predicate")
        if type(self.semantic_revision) is not int or self.semantic_revision != 1:
            raise ValueError("V1のsemantic revisionは1でなければなりません")
        if type(self.subject_kind) is not GoalCommitmentSemanticSubjectKind:
            raise ValueError("subject kindの型が不正です")
        if self.subject_kind is GoalCommitmentSemanticSubjectKind.SELF:
            if self.subject_ref is not None:
                raise ValueError("SELFはsubject refを持てません")
        else:
            if not isinstance(self.subject_ref, str):
                raise ValueError("REFERENCEにはsubject refが必要です")
            require_identifier(self.subject_ref, "subject_ref")
        if type(self.polarity) is not GoalCommitmentSemanticPolarity:
            raise ValueError("polarityの型が不正です")
        if self.degree is not None and (
            type(self.degree) not in (int, float)
            or not 0 <= self.degree <= 1
            or not isfinite(self.degree)
        ):
            raise ValueError("degreeは有限の0から1またはNoneでなければなりません")
        object.__setattr__(self, "value", freeze_json(self.value))

    def reference_ids(self) -> tuple[str, ...]:
        return () if self.subject_ref is None else (self.subject_ref,)

    def to_dict(self) -> dict[str, object]:
        return {
            "semantic_ref": self.semantic_ref,
            "semantic_revision": self.semantic_revision,
            "subject_kind": self.subject_kind.value,
            "subject_ref": self.subject_ref,
            "predicate": self.predicate,
            "value": thaw_json(self.value),
            "polarity": self.polarity.value,
            "degree": self.degree,
        }

    @classmethod
    def from_dict(cls, value: object) -> "GoalCommitmentSemanticSpec":
        fields = {
            "semantic_ref",
            "semantic_revision",
            "subject_kind",
            "subject_ref",
            "predicate",
            "value",
            "polarity",
            "degree",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError("semantic specのfield集合が不正です")
        return cls(
            value["semantic_ref"],
            value["semantic_revision"],
            GoalCommitmentSemanticSubjectKind(value["subject_kind"]),
            value["subject_ref"],
            value["predicate"],
            cast(JsonValue, value["value"]),
            GoalCommitmentSemanticPolarity(value["polarity"]),
            value["degree"],
        )


def require_semantic_spec(spec: object, semantic_ref: str | None) -> GoalCommitmentSemanticSpec:
    if type(spec) is not GoalCommitmentSemanticSpec:
        raise ValueError("exact typed semantic specが必要です")
    spec.__post_init__()
    if spec.semantic_ref != semantic_ref:
        raise ValueError("semantic refとspecが一致しません")
    return spec
