from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping, cast

from app.domain.semantic_utterance import (
    InterpersonalContentContext,
    SemanticTarget,
    SemanticUtterancePlan,
)


SemanticValueStatus = Literal["known", "unknown"]
SemanticPolarity = Literal["present", "absent"]
SemanticDegree = Literal["low", "moderate", "high", "very_high"]
SemanticCertainty = Literal["low", "medium", "high"]
SemanticSummaryMode = Literal["detail", "overview"]
SemanticRealizationPolicy = Literal["required", "optional"]

_ALLOWED_STATUS = frozenset({"known", "unknown"})
_ALLOWED_POLARITY = frozenset({"present", "absent"})
_ALLOWED_DEGREE = frozenset({"low", "moderate", "high", "very_high"})
_ALLOWED_CERTAINTY = frozenset({"low", "medium", "high"})
_ALLOWED_SUMMARY_MODE = frozenset({"detail", "overview"})
_ALLOWED_REALIZATION_POLICY = frozenset({"required", "optional"})
_ALLOWED_LENGTH = frozenset({"short", "normal", "long"})
_ALLOWED_DISCLOSURE = frozenset({"none", "brief"})

LegacyStateMapping = tuple[
    SemanticValueStatus,
    SemanticPolarity | None,
    SemanticDegree | None,
    SemanticSummaryMode,
]

_LEGACY_STATE_TO_V2: dict[str, LegacyStateMapping] = {
    "absent": ("known", "absent", None, "detail"),
    "present": ("known", "present", None, "detail"),
    "low": ("known", "present", "low", "detail"),
    "moderate": ("known", "present", "moderate", "detail"),
    "high": ("known", "present", "high", "detail"),
    "very_high": ("known", "present", "very_high", "detail"),
    "unknown": ("unknown", None, None, "detail"),
    "overview": ("known", None, None, "overview"),
}


@dataclass(frozen=True, slots=True)
class SemanticValue:
    """直交化した意味値。certaintyは値availabilityとは独立したepistemic commitment。"""

    status: SemanticValueStatus
    polarity: SemanticPolarity | None
    degree: SemanticDegree | None
    certainty: SemanticCertainty

    def __post_init__(self) -> None:
        if self.status not in _ALLOWED_STATUS:
            raise ValueError("SemanticValue.statusが不正です。")
        if self.polarity is not None and self.polarity not in _ALLOWED_POLARITY:
            raise ValueError("SemanticValue.polarityが不正です。")
        if self.degree is not None and self.degree not in _ALLOWED_DEGREE:
            raise ValueError("SemanticValue.degreeが不正です。")
        if self.certainty not in _ALLOWED_CERTAINTY:
            raise ValueError("SemanticValue.certaintyが不正です。")

        if self.status == "unknown":
            if self.polarity is not None or self.degree is not None:
                raise ValueError("unknown valueはpolarity/degreeを持てません。")
            return

        if self.degree is not None and self.polarity != "present":
            raise ValueError("degreeを持つknown valueはpolarity=presentが必要です。")
        if self.polarity == "absent" and self.degree is not None:
            raise ValueError("absent valueはdegreeを持てません。")

    def as_context(self) -> dict[str, object]:
        return {
            "status": self.status,
            "polarity": self.polarity,
            "degree": self.degree,
            "certainty": self.certainty,
        }


@dataclass(frozen=True, slots=True)
class SemanticPropositionV2:
    """Legacy state enumを直交facetへ分解したcanonical proposition。"""

    proposition_id: str
    kind: str
    predicate: str
    value: SemanticValue
    concept: str | None = None
    summary_mode: SemanticSummaryMode = "detail"
    realization_policy: SemanticRealizationPolicy = "required"
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.proposition_id, str) or not self.proposition_id.strip():
            raise ValueError("proposition_idは空にできません。")
        if (
            not isinstance(self.kind, str)
            or not self.kind.strip()
            or not isinstance(self.predicate, str)
            or not self.predicate.strip()
        ):
            raise ValueError("SemanticPropositionV2のkind/predicateは空にできません。")
        if self.summary_mode not in _ALLOWED_SUMMARY_MODE:
            raise ValueError("summary_modeが不正です。")
        if self.realization_policy not in _ALLOWED_REALIZATION_POLICY:
            raise ValueError("realization_policyが不正です。")
        if self.concept is not None and (
            not isinstance(self.concept, str) or not self.concept.strip()
        ):
            raise ValueError("conceptはnullまたは非空文字列にしてください。")
        if any(
            not isinstance(item, str) or not item.strip()
            for item in self.evidence_refs
        ):
            raise ValueError("evidence_refsに空文字または非文字列は使用できません。")

        if self.summary_mode == "overview":
            if (
                self.value.status != "known"
                or self.value.polarity is not None
                or self.value.degree is not None
            ):
                raise ValueError(
                    "overview propositionはknownかつpolarity/degreeなしである必要があります。"
                )
            return

        if self.value.status == "known" and self.value.polarity is None:
            raise ValueError("known detail propositionはpolarityが必要です。")

    def as_context(self) -> dict[str, object]:
        return {
            "proposition_id": self.proposition_id,
            "kind": self.kind,
            "predicate": self.predicate,
            "value": self.value.as_context(),
            "concept": self.concept,
            "summary_mode": self.summary_mode,
            "realization_policy": self.realization_policy,
            "evidence_refs": list(self.evidence_refs),
        }

    def legacy_state(self) -> str:
        return LegacySemanticStateAdapter.to_legacy(
            value=self.value,
            summary_mode=self.summary_mode,
        )


class LegacySemanticStateAdapter:
    """Legacy state enumとv2直交facetの意味変換を一箇所に固定する。"""

    @staticmethod
    def from_legacy(
        *,
        state: str,
        certainty: str,
    ) -> tuple[SemanticValue, SemanticSummaryMode]:
        mapped = _LEGACY_STATE_TO_V2.get(state)
        if mapped is None:
            raise ValueError(f"未対応のLegacy semantic stateです: {state}")
        if certainty not in _ALLOWED_CERTAINTY:
            raise ValueError(f"未対応のSemantic certaintyです: {certainty}")

        status, polarity, degree, summary_mode = mapped
        return (
            SemanticValue(
                status=status,
                polarity=polarity,
                degree=degree,
                certainty=cast(SemanticCertainty, certainty),
            ),
            summary_mode,
        )

    @staticmethod
    def to_legacy(*, value: SemanticValue, summary_mode: str) -> str:
        if summary_mode not in _ALLOWED_SUMMARY_MODE:
            raise ValueError(f"未対応のsummary_modeです: {summary_mode}")

        if summary_mode == "overview":
            if (
                value.status == "known"
                and value.polarity is None
                and value.degree is None
            ):
                return "overview"
            raise ValueError("overviewとしてLegacy stateへ変換できないv2 valueです。")

        if value.status == "unknown":
            if value.polarity is None and value.degree is None:
                return "unknown"
            raise ValueError("unknownとしてLegacy stateへ変換できないv2 valueです。")

        if value.polarity == "absent" and value.degree is None:
            return "absent"
        if value.polarity == "present" and value.degree is None:
            return "present"
        if value.polarity == "present" and value.degree in _ALLOWED_DEGREE:
            return cast(str, value.degree)

        raise ValueError("Legacy stateへ一意に変換できないv2 valueです。")


@dataclass(frozen=True, slots=True)
class SemanticUtterancePlanV2:
    """v2 propositionを持つ「何を言うか」のcanonical typed plan。"""

    speech_act: str
    target: SemanticTarget | None = None
    propositions: tuple[SemanticPropositionV2, ...] = field(default_factory=tuple)
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
        if not isinstance(self.speech_act, str) or not self.speech_act.strip():
            raise ValueError("speech_actは空にできません。")
        if self.response_length not in _ALLOWED_LENGTH:
            raise ValueError("response_lengthが不正です。")
        if self.self_disclosure not in _ALLOWED_DISCLOSURE:
            raise ValueError("self_disclosureが不正です。")
        if isinstance(self.question_budget, bool) or self.question_budget not in {0, 1}:
            raise ValueError("question_budgetは0または1にしてください。")
        if (
            isinstance(self.new_direction_budget, bool)
            or self.new_direction_budget not in {0, 1}
        ):
            raise ValueError("new_direction_budgetは0または1にしてください。")

        proposition_ids = [item.proposition_id for item in self.propositions]
        if len(proposition_ids) != len(set(proposition_ids)):
            raise ValueError("SemanticUtterancePlanV2内のproposition_idは一意にしてください。")

        for values in (
            self.required_content,
            self.optional_content,
            self.forbidden_additions,
            self.reasons,
        ):
            if any(
                not isinstance(item, str) or not item.strip()
                for item in values
            ):
                raise ValueError(
                    "SemanticUtterancePlanV2の文字列配列に空文字または非文字列は使用できません。"
                )

        if any(
            not isinstance(key, str)
            or not key.strip()
            or not isinstance(value, str)
            or not value.strip()
            for key, value in self.discourse_context.items()
        ):
            raise ValueError(
                "discourse_contextは非空文字列のkey/valueだけを使用してください。"
            )

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
    def from_legacy(cls, plan: SemanticUtterancePlan) -> SemanticUtterancePlanV2:
        propositions: list[SemanticPropositionV2] = []
        for index, proposition in enumerate(plan.propositions):
            value, summary_mode = LegacySemanticStateAdapter.from_legacy(
                state=proposition.state,
                certainty=proposition.certainty,
            )
            propositions.append(
                SemanticPropositionV2(
                    proposition_id=f"proposition:{index}:{proposition.predicate}",
                    kind=proposition.kind,
                    predicate=proposition.predicate,
                    value=value,
                    concept=proposition.concept,
                    summary_mode=summary_mode,
                    realization_policy="required" if index == 0 else "optional",
                    evidence_refs=proposition.evidence_refs,
                )
            )

        return cls(
            speech_act=plan.speech_act,
            target=plan.target,
            propositions=tuple(propositions),
            required_content=plan.required_content,
            optional_content=plan.optional_content,
            forbidden_additions=plan.forbidden_additions,
            response_length=plan.response_length,
            self_disclosure=plan.self_disclosure,
            question_budget=plan.question_budget,
            new_direction_budget=plan.new_direction_budget,
            interpersonal=plan.interpersonal,
            discourse_context=dict(plan.discourse_context),
            reasons=plan.reasons,
        )

    @classmethod
    def from_context(cls, value: object) -> SemanticUtterancePlanV2 | None:
        if not isinstance(value, Mapping):
            return None

        required_plan_keys = {
            "speech_act",
            "target",
            "propositions",
            "required_content",
            "optional_content",
            "forbidden_additions",
            "response_length",
            "self_disclosure",
            "question_budget",
            "new_direction_budget",
            "interpersonal",
            "discourse_context",
            "reasons",
        }
        if not required_plan_keys.issubset(value.keys()):
            return None

        speech_act = cls._required_string(value.get("speech_act"))
        if speech_act is None:
            return None

        target = cls._target_from_context(value.get("target"))
        if value.get("target") is not None and target is None:
            return None

        raw_propositions = value.get("propositions")
        if not isinstance(raw_propositions, (list, tuple)):
            return None

        propositions: list[SemanticPropositionV2] = []
        for item in raw_propositions:
            proposition = cls._proposition_from_context(item)
            if proposition is None:
                return None
            propositions.append(proposition)

        required_content = cls._strict_strings(value.get("required_content"))
        optional_content = cls._strict_strings(value.get("optional_content"))
        forbidden_additions = cls._strict_strings(value.get("forbidden_additions"))
        reasons = cls._strict_strings(value.get("reasons"))
        if (
            required_content is None
            or optional_content is None
            or forbidden_additions is None
            or reasons is None
        ):
            return None

        response_length = cls._required_string(value.get("response_length"))
        self_disclosure = cls._required_string(value.get("self_disclosure"))
        if (
            response_length not in _ALLOWED_LENGTH
            or self_disclosure not in _ALLOWED_DISCLOSURE
        ):
            return None

        question_budget = cls._strict_budget(value.get("question_budget"))
        new_direction_budget = cls._strict_budget(value.get("new_direction_budget"))
        if question_budget is None or new_direction_budget is None:
            return None

        interpersonal = cls._interpersonal_from_context(value.get("interpersonal"))
        if interpersonal is None:
            return None

        discourse_context = cls._discourse_from_context(value.get("discourse_context"))
        if discourse_context is None:
            return None

        try:
            return cls(
                speech_act=speech_act,
                target=target,
                propositions=tuple(propositions),
                required_content=required_content,
                optional_content=optional_content,
                forbidden_additions=forbidden_additions,
                response_length=cast(str, response_length),
                self_disclosure=cast(str, self_disclosure),
                question_budget=question_budget,
                new_direction_budget=new_direction_budget,
                interpersonal=interpersonal,
                discourse_context=discourse_context,
                reasons=reasons,
            )
        except ValueError:
            return None

    @classmethod
    def _target_from_context(cls, value: object) -> SemanticTarget | None:
        if value is None:
            return None
        if not isinstance(value, Mapping):
            return None
        target_type = cls._required_string(value.get("type"))
        target_id = cls._required_string(value.get("id"))
        if target_type is None or target_id is None:
            return None
        try:
            return SemanticTarget(target_type, target_id)
        except ValueError:
            return None

    @classmethod
    def _proposition_from_context(
        cls,
        value: object,
    ) -> SemanticPropositionV2 | None:
        if not isinstance(value, Mapping):
            return None

        required_keys = {
            "proposition_id",
            "kind",
            "predicate",
            "value",
            "concept",
            "summary_mode",
            "realization_policy",
            "evidence_refs",
        }
        if not required_keys.issubset(value.keys()):
            return None

        proposition_id = cls._required_string(value.get("proposition_id"))
        kind = cls._required_string(value.get("kind"))
        predicate = cls._required_string(value.get("predicate"))
        summary_mode = cls._required_string(value.get("summary_mode"))
        realization_policy = cls._required_string(value.get("realization_policy"))
        if (
            proposition_id is None
            or kind is None
            or predicate is None
            or summary_mode not in _ALLOWED_SUMMARY_MODE
            or realization_policy not in _ALLOWED_REALIZATION_POLICY
        ):
            return None

        raw_value = value.get("value")
        semantic_value = cls._semantic_value_from_context(raw_value)
        if semantic_value is None:
            return None

        concept_value = value.get("concept")
        if concept_value is None:
            concept = None
        else:
            concept = cls._required_string(concept_value)
            if concept is None:
                return None

        evidence_refs = cls._strict_strings(value.get("evidence_refs"))
        if evidence_refs is None:
            return None

        try:
            return SemanticPropositionV2(
                proposition_id=proposition_id,
                kind=kind,
                predicate=predicate,
                value=semantic_value,
                concept=concept,
                summary_mode=cast(SemanticSummaryMode, summary_mode),
                realization_policy=cast(
                    SemanticRealizationPolicy,
                    realization_policy,
                ),
                evidence_refs=evidence_refs,
            )
        except ValueError:
            return None

    @classmethod
    def _semantic_value_from_context(cls, value: object) -> SemanticValue | None:
        if not isinstance(value, Mapping):
            return None
        required_keys = {"status", "polarity", "degree", "certainty"}
        if not required_keys.issubset(value.keys()):
            return None

        status = cls._required_string(value.get("status"))
        certainty = cls._required_string(value.get("certainty"))
        if status not in _ALLOWED_STATUS or certainty not in _ALLOWED_CERTAINTY:
            return None

        polarity_ok, polarity = cls._nullable_enum(
            value.get("polarity"),
            allowed=_ALLOWED_POLARITY,
        )
        degree_ok, degree = cls._nullable_enum(
            value.get("degree"),
            allowed=_ALLOWED_DEGREE,
        )
        if not polarity_ok or not degree_ok:
            return None

        try:
            return SemanticValue(
                status=cast(SemanticValueStatus, status),
                polarity=cast(SemanticPolarity | None, polarity),
                degree=cast(SemanticDegree | None, degree),
                certainty=cast(SemanticCertainty, certainty),
            )
        except ValueError:
            return None

    @classmethod
    def _interpersonal_from_context(
        cls,
        value: object,
    ) -> InterpersonalContentContext | None:
        if not isinstance(value, Mapping):
            return None
        keys = {
            "disclosure_permission",
            "boundary_sensitivity",
            "social_distance",
            "current_tension",
        }
        if not keys.issubset(value.keys()):
            return None

        normalized = {
            key: cls._required_string(value.get(key))
            for key in keys
        }
        if any(item is None for item in normalized.values()):
            return None

        return InterpersonalContentContext(
            disclosure_permission=cast(str, normalized["disclosure_permission"]),
            boundary_sensitivity=cast(str, normalized["boundary_sensitivity"]),
            social_distance=cast(str, normalized["social_distance"]),
            current_tension=cast(str, normalized["current_tension"]),
        )

    @staticmethod
    def _discourse_from_context(value: object) -> dict[str, str] | None:
        if not isinstance(value, Mapping):
            return None

        normalized: dict[str, str] = {}
        for key, item in value.items():
            if (
                not isinstance(key, str)
                or not key.strip()
                or not isinstance(item, str)
                or not item.strip()
            ):
                return None
            normalized[key.strip()] = item.strip()
        return normalized

    @staticmethod
    def _nullable_enum(
        value: object,
        *,
        allowed: frozenset[str],
    ) -> tuple[bool, str | None]:
        if value is None:
            return True, None
        if not isinstance(value, str):
            return False, None
        normalized = value.strip()
        if not normalized or normalized not in allowed:
            return False, None
        return True, normalized

    @staticmethod
    def _required_string(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized if normalized else None

    @staticmethod
    def _strict_strings(value: object) -> tuple[str, ...] | None:
        if not isinstance(value, (list, tuple)):
            return None

        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                return None
            normalized.append(item.strip())
        return tuple(normalized)

    @staticmethod
    def _strict_budget(value: object) -> int | None:
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value if value in {0, 1} else None
