from __future__ import annotations

from dataclasses import dataclass, field, replace
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
_ALLOWED_VALUE_STATUS = frozenset({"known", "unknown"})
_ALLOWED_POLARITY = frozenset({"present", "absent"})
_ALLOWED_DEGREE = frozenset({"low", "moderate", "high", "very_high"})
_ALLOWED_CERTAINTY = frozenset({"low", "medium", "high"})
_ALLOWED_SUMMARY_MODE = frozenset({"detail", "overview"})
_ALLOWED_REALIZATION_POLICY = frozenset({"required", "optional"})
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
class SemanticValue:
    """Propositionの値意味を直交facetで保持するv2正規表現。"""

    status: str
    polarity: str | None = None
    degree: str | None = None
    certainty: str = "high"

    def __post_init__(self) -> None:
        if self.status not in _ALLOWED_VALUE_STATUS:
            raise ValueError("SemanticValue.statusが不正です。")
        if self.polarity is not None and self.polarity not in _ALLOWED_POLARITY:
            raise ValueError("SemanticValue.polarityが不正です。")
        if self.degree is not None and self.degree not in _ALLOWED_DEGREE:
            raise ValueError("SemanticValue.degreeが不正です。")
        if self.certainty not in _ALLOWED_CERTAINTY:
            raise ValueError("SemanticValue.certaintyが不正です。")
        if self.status == "unknown" and (self.polarity is not None or self.degree is not None):
            raise ValueError("unknown valueはpolarity/degreeを持てません。")
        if self.polarity == "absent" and self.degree is not None:
            raise ValueError("absent valueはdegreeを持てません。")
        if self.degree is not None and self.polarity != "present":
            raise ValueError("degreeを持つvalueはpolarity=presentが必要です。")

    def as_context(self) -> dict[str, object]:
        return {
            "status": self.status,
            "polarity": self.polarity,
            "degree": self.degree,
            "certainty": self.certainty,
        }

    def legacy_state(self, *, summary_mode: str = "detail") -> str:
        """移行互換用。新規意味判定で使用しない。"""

        if summary_mode == "overview":
            return "overview"
        if self.status == "unknown":
            return "unknown"
        if self.polarity == "absent":
            return "absent"
        if self.degree is not None:
            return self.degree
        if self.polarity == "present":
            return "present"
        raise ValueError("SemanticValueをlegacy stateへ変換できません。")

    @classmethod
    def from_legacy_state(cls, state: str, *, certainty: str) -> "SemanticValue":
        if state not in _ALLOWED_STATES:
            raise ValueError("legacy SemanticProposition.stateが不正です。")
        if state == "unknown":
            return cls(status="unknown", certainty=certainty)
        if state == "absent":
            return cls(status="known", polarity="absent", certainty=certainty)
        if state in _ALLOWED_DEGREE:
            return cls(
                status="known",
                polarity="present",
                degree=state,
                certainty=certainty,
            )
        if state == "present":
            return cls(status="known", polarity="present", certainty=certainty)
        if state == "overview":
            return cls(status="known", certainty=certainty)
        raise ValueError("legacy stateをSemanticValueへ変換できません。")

    @classmethod
    def from_context(cls, value: object) -> "SemanticValue" | None:
        if not isinstance(value, Mapping):
            return None
        status = str(value.get("status") or "").strip()
        certainty = str(value.get("certainty") or "").strip()
        if status not in _ALLOWED_VALUE_STATUS or certainty not in _ALLOWED_CERTAINTY:
            return None
        polarity_value = value.get("polarity")
        polarity = (
            str(polarity_value).strip()
            if polarity_value is not None and str(polarity_value).strip()
            else None
        )
        degree_value = value.get("degree")
        degree = (
            str(degree_value).strip()
            if degree_value is not None and str(degree_value).strip()
            else None
        )
        try:
            return cls(
                status=status,
                polarity=polarity,
                degree=degree,
                certainty=certainty,
            )
        except ValueError:
            return None


@dataclass(frozen=True, slots=True)
class SemanticProposition:
    """Characterが表現すべき事実意味。

    ``state`` / ``certainty`` は移行互換field。v2意味authorityは ``value`` と
    ``summary_mode`` に置く。新規Productコードはlegacy stateから意味判定しない。
    """

    kind: str
    predicate: str
    state: str | None = None
    certainty: str = "high"
    concept: str | None = None
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    value: SemanticValue | None = None
    summary_mode: str = "detail"
    proposition_id: str = ""
    realization_policy: str = ""

    def __post_init__(self) -> None:
        if not self.kind.strip() or not self.predicate.strip():
            raise ValueError("SemanticPropositionのkind/predicateは空にできません。")
        if self.certainty not in _ALLOWED_CERTAINTY:
            raise ValueError("SemanticProposition.certaintyが不正です。")
        if self.summary_mode not in _ALLOWED_SUMMARY_MODE:
            raise ValueError("SemanticProposition.summary_modeが不正です。")
        if self.realization_policy and self.realization_policy not in _ALLOWED_REALIZATION_POLICY:
            raise ValueError("SemanticProposition.realization_policyが不正です。")
        if any(not item.strip() for item in self.evidence_refs):
            raise ValueError("evidence_refsに空文字は使用できません。")
        if self.proposition_id and not self.proposition_id.strip():
            raise ValueError("proposition_idに空白のみは使用できません。")

        normalized_summary_mode = self.summary_mode
        normalized_value = self.value
        if normalized_value is None:
            legacy_state = self.state or "unknown"
            if legacy_state not in _ALLOWED_STATES:
                raise ValueError("SemanticProposition.stateが不正です。")
            normalized_value = SemanticValue.from_legacy_state(
                legacy_state,
                certainty=self.certainty,
            )
            if legacy_state == "overview":
                normalized_summary_mode = "overview"
        else:
            if normalized_value.certainty != self.certainty:
                raise ValueError("SemanticValue.certaintyと互換certaintyが一致しません。")
            if self.state is not None:
                if self.state not in _ALLOWED_STATES:
                    raise ValueError("SemanticProposition.stateが不正です。")
                expected_legacy = normalized_value.legacy_state(
                    summary_mode=normalized_summary_mode
                )
                if self.state != expected_legacy:
                    raise ValueError("legacy stateとv2 SemanticValueが矛盾しています。")

        if normalized_summary_mode == "overview":
            if (
                normalized_value.status != "known"
                or normalized_value.polarity is not None
                or normalized_value.degree is not None
            ):
                raise ValueError("overview propositionはknownかつpolarity/degreeなしで表します。")
        elif normalized_value.status == "known" and normalized_value.polarity is None:
            raise ValueError("detail known propositionにはpolarityが必要です。")

        legacy_state = normalized_value.legacy_state(summary_mode=normalized_summary_mode)
        object.__setattr__(self, "value", normalized_value)
        object.__setattr__(self, "summary_mode", normalized_summary_mode)
        object.__setattr__(self, "state", legacy_state)
        object.__setattr__(self, "certainty", normalized_value.certainty)
        if self.proposition_id:
            object.__setattr__(self, "proposition_id", self.proposition_id.strip())

    def as_context(self) -> dict[str, object]:
        assert self.value is not None
        return {
            "proposition_id": self.proposition_id,
            "kind": self.kind,
            "predicate": self.predicate,
            "value": self.value.as_context(),
            "summary_mode": self.summary_mode,
            "realization_policy": self.realization_policy,
            "concept": self.concept,
            "evidence_refs": list(self.evidence_refs),
            # 移行互換。新規Productコードはこのfieldから意味判定しない。
            "state": self.state,
            "certainty": self.certainty,
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
        if isinstance(self.question_budget, bool) or self.question_budget not in {0, 1}:
            raise ValueError("question_budgetは0または1にしてください。")
        if (
            isinstance(self.new_direction_budget, bool)
            or self.new_direction_budget not in {0, 1}
        ):
            raise ValueError("new_direction_budgetは0または1にしてください。")
        for values in (
            self.required_content,
            self.optional_content,
            self.forbidden_additions,
            self.reasons,
        ):
            if any(not item.strip() for item in values):
                raise ValueError("SemanticUtterancePlanの文字列配列に空文字は使用できません。")

        normalized: list[SemanticProposition] = []
        seen_ids: set[str] = set()
        for index, proposition in enumerate(self.propositions):
            proposition_id = proposition.proposition_id or f"proposition:{index}:{proposition.predicate}"
            realization_policy = proposition.realization_policy or (
                "required" if index == 0 else "optional"
            )
            if proposition_id in seen_ids:
                raise ValueError("SemanticProposition.proposition_idが重複しています。")
            seen_ids.add(proposition_id)
            normalized.append(
                replace(
                    proposition,
                    proposition_id=proposition_id,
                    realization_policy=realization_policy,
                )
            )
        object.__setattr__(self, "propositions", tuple(normalized))

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
            for index, item in enumerate(raw_propositions):
                if not isinstance(item, Mapping):
                    continue
                kind = str(item.get("kind") or "").strip()
                predicate = str(item.get("predicate") or "").strip()
                if not kind or not predicate:
                    continue

                value_v2 = SemanticValue.from_context(item.get("value"))
                certainty = str(item.get("certainty") or "").strip()
                if value_v2 is not None:
                    certainty = value_v2.certainty
                elif certainty not in _ALLOWED_CERTAINTY:
                    certainty = "low"

                state_value = item.get("state")
                state = (
                    str(state_value).strip()
                    if state_value is not None and str(state_value).strip()
                    else None
                )
                if value_v2 is None:
                    if state not in _ALLOWED_STATES:
                        state = "unknown"

                summary_mode = str(item.get("summary_mode") or "").strip()
                if summary_mode not in _ALLOWED_SUMMARY_MODE:
                    summary_mode = "overview" if state == "overview" else "detail"

                concept_value = item.get("concept")
                concept = (
                    str(concept_value).strip()
                    if concept_value is not None and str(concept_value).strip()
                    else None
                )
                evidence_refs = cls._strings(item.get("evidence_refs"))
                proposition_id = str(item.get("proposition_id") or "").strip()
                realization_policy = str(item.get("realization_policy") or "").strip()
                if realization_policy not in _ALLOWED_REALIZATION_POLICY:
                    realization_policy = "required" if index == 0 else "optional"

                try:
                    propositions.append(
                        SemanticProposition(
                            kind=kind,
                            predicate=predicate,
                            state=state,
                            certainty=certainty,
                            concept=concept,
                            evidence_refs=evidence_refs,
                            value=value_v2,
                            summary_mode=summary_mode,
                            proposition_id=proposition_id,
                            realization_policy=realization_policy,
                        )
                    )
                except ValueError:
                    continue

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
            question_budget=cls._binary_budget(value.get("question_budget")),
            new_direction_budget=cls._binary_budget(value.get("new_direction_budget")),
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

    @staticmethod
    def _binary_budget(value: object) -> int:
        if isinstance(value, bool):
            return 0
        return 1 if value == 1 else 0
