from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol, TypeVar, cast

from app.domain.contracts.common import (
    JsonValue,
    require_aware,
    timestamp_to_json,
    utc_instant,
)
from app.domain.llm import (
    LLMActivationPolicy,
    LLMExecutionPolicy,
    LLMFailurePolicy,
    LLMRoleDescriptor,
    LLMRoleRequest,
    LLMRoleResult,
    LLMRoleStatus,
    LLMStalePolicy,
    StructuredPayload,
    validate_role_exchange,
)
from app.usecases.ports.llm import LLMRolePort

from .authority import SemanticVerificationAuthority
from .contracts import (
    BlindSemanticUnit,
    BlindSemanticUnitKind,
    BlindUnitAccounting,
    BlindUnitAccountingRelation,
    BlindUtteranceObservation,
    BlindUtteranceObservationCandidate,
    CertaintyRelation,
    DegreeRelation,
    ExecutionRelation,
    PlanRelationObservation,
    PlanRelationObservationCandidate,
    PolarityRelation,
    PropositionRelation,
    PropositionSemanticObservation,
    SelfDisclosureRelation,
    SemanticAcceptance,
    SemanticRelationObservation,
    SemanticVerificationContextSnapshot,
    SemanticVerificationEligibilityView,
    SemanticVerificationError,
    SemanticVerificationFailureCode,
    SpeechActBudgetObservation,
    UtteranceEvidenceRef,
)

BLIND_ROLE_ID = "semantic_verification_blind_inventory"
BLIND_INPUT_SCHEMA = "semantic.verification.blind.context.v1"
BLIND_OUTPUT_SCHEMA = "semantic.verification.blind.candidate.v1"
RELATION_ROLE_ID = "semantic_verification_plan_relation"
RELATION_INPUT_SCHEMA = "semantic.verification.relation.context.v1"
RELATION_OUTPUT_SCHEMA = "semantic.verification.relation.candidate.v1"


@dataclass(frozen=True, slots=True)
class SemanticVerificationPolicy:
    blind_execution: LLMExecutionPolicy
    relation_execution: LLMExecutionPolicy

    def __post_init__(self) -> None:
        if not isinstance(self.blind_execution, LLMExecutionPolicy):
            raise ValueError("blind_execution が不正です")
        if not isinstance(self.relation_execution, LLMExecutionPolicy):
            raise ValueError("relation_execution が不正です")


@dataclass(frozen=True, slots=True)
class SemanticVerificationRun:
    blind_result: LLMRoleResult
    relation_result: LLMRoleResult
    blind_observation: BlindUtteranceObservation
    relation_observation: PlanRelationObservation
    semantic_observation: SemanticRelationObservation
    acceptance: SemanticAcceptance


class SemanticVerificationLiveStatePort(Protocol):
    async def current_state(
        self,
        snapshot: SemanticVerificationContextSnapshot,
    ) -> SemanticVerificationEligibilityView: ...


def blind_descriptor(policy: SemanticVerificationPolicy) -> LLMRoleDescriptor:
    return LLMRoleDescriptor(
        BLIND_ROLE_ID,
        "Planを見ずにactual utteranceのmaterial semantic unitを独立inventoryする",
        BLIND_INPUT_SCHEMA,
        BLIND_OUTPUT_SCHEMA,
        "blind_semantic_inventory_candidate_only",
        LLMActivationPolicy.REQUIRED,
        LLMFailurePolicy.FAIL_CLOSED,
        policy.blind_execution,
    )


def relation_descriptor(policy: SemanticVerificationPolicy) -> LLMRoleDescriptor:
    return LLMRoleDescriptor(
        RELATION_ROLE_ID,
        "frozen blind unitsを保持しPlan propositionとのsemantic relationを観測する",
        RELATION_INPUT_SCHEMA,
        RELATION_OUTPUT_SCHEMA,
        "plan_relation_candidate_only",
        LLMActivationPolicy.REQUIRED,
        LLMFailurePolicy.FAIL_CLOSED,
        policy.relation_execution,
    )


def build_blind_request(
    snapshot: SemanticVerificationContextSnapshot,
    *,
    created_at: datetime,
    policy: SemanticVerificationPolicy,
) -> LLMRoleRequest:
    require_aware(created_at, "created_at")
    if utc_instant(created_at) < utc_instant(snapshot.captured_at):
        raise ValueError("blind requestはsnapshotより前に作成できません")
    payload: JsonValue = cast(
        JsonValue,
        {
            "verification_id": snapshot.verification_id,
            "utterance_id": snapshot.utterance.utterance_id,
            "segments": _utterance_segments(snapshot),
            "captured_at": timestamp_to_json(snapshot.captured_at),
        },
    )
    return LLMRoleRequest(
        snapshot.blind_request_id,
        BLIND_ROLE_ID,
        StructuredPayload(BLIND_INPUT_SCHEMA, payload),
        snapshot.source_event_ids,
        snapshot.revisions,
        (),
        snapshot.llm_priority,
        snapshot.interruptibility,
        LLMStalePolicy.REJECT,
        policy.blind_execution,
        created_at,
        snapshot.trace_id,
    )


def build_relation_request(
    snapshot: SemanticVerificationContextSnapshot,
    blind: BlindUtteranceObservation,
    *,
    created_at: datetime,
    policy: SemanticVerificationPolicy,
) -> LLMRoleRequest:
    require_aware(created_at, "created_at")
    if blind.candidate.utterance_id != snapshot.utterance.utterance_id:
        raise ValueError("blind observationが別Utteranceを参照しています")
    if utc_instant(created_at) < utc_instant(blind.committed_at):
        raise ValueError("relation requestはblind observation commitより前に作成できません")
    payload: JsonValue = cast(
        JsonValue,
        {
            "verification_id": snapshot.verification_id,
            "pair": snapshot.pair_dict(),
            "semantic_plan": snapshot.semantic_plan.to_dict(),
            "utterance": {
                "utterance_id": snapshot.utterance.utterance_id,
                "segments": _utterance_segments(snapshot),
            },
            "blind_observation": blind.to_dict(),
        },
    )
    return LLMRoleRequest(
        snapshot.relation_request_id,
        RELATION_ROLE_ID,
        StructuredPayload(RELATION_INPUT_SCHEMA, payload),
        snapshot.source_event_ids,
        snapshot.revisions,
        (),
        snapshot.llm_priority,
        snapshot.interruptibility,
        LLMStalePolicy.REJECT,
        policy.relation_execution,
        created_at,
        snapshot.trace_id,
    )


def parse_blind_candidate(
    value: object,
    *,
    observed_at: datetime,
) -> BlindUtteranceObservationCandidate:
    item = _mapping(value, "blind candidate")
    required = {"candidate_id", "request_id", "utterance_id", "units"}
    if set(item) != required:
        raise ValueError("blind candidate fieldがschemaと一致しません")
    return BlindUtteranceObservationCandidate(
        _string(item["candidate_id"], "candidate_id"),
        _string(item["request_id"], "request_id"),
        _string(item["utterance_id"], "utterance_id"),
        tuple(_blind_unit(part) for part in _array(item["units"], "units")),
        observed_at,
    )


def parse_relation_candidate(
    value: object,
    *,
    observed_at: datetime,
) -> PlanRelationObservationCandidate:
    item = _mapping(value, "relation candidate")
    required = {
        "candidate_id",
        "request_id",
        "semantic_plan_id",
        "utterance_id",
        "blind_observation_id",
        "proposition_observations",
        "blind_unit_accounting",
        "budget_observation",
        "self_disclosure_relation",
    }
    if set(item) != required:
        raise ValueError("relation candidate fieldがschemaと一致しません")
    budget = _mapping(item["budget_observation"], "budget_observation")
    if set(budget) != {"directed_question_count", "new_direction_count"}:
        raise ValueError("budget fieldがschemaと一致しません")
    return PlanRelationObservationCandidate(
        _string(item["candidate_id"], "candidate_id"),
        _string(item["request_id"], "request_id"),
        _string(item["semantic_plan_id"], "semantic_plan_id"),
        _string(item["utterance_id"], "utterance_id"),
        _string(item["blind_observation_id"], "blind_observation_id"),
        tuple(
            _proposition_observation(part)
            for part in _array(
                item["proposition_observations"],
                "proposition_observations",
            )
        ),
        tuple(
            _accounting(part)
            for part in _array(item["blind_unit_accounting"], "blind_unit_accounting")
        ),
        SpeechActBudgetObservation(
            _non_negative_int(
                budget["directed_question_count"],
                "directed_question_count",
            ),
            _non_negative_int(budget["new_direction_count"], "new_direction_count"),
        ),
        _enum(
            SelfDisclosureRelation,
            item["self_disclosure_relation"],
            "self_disclosure_relation",
        ),
        observed_at,
    )


class SemanticVerifier:
    def __init__(
        self,
        port: LLMRolePort,
        live_state: SemanticVerificationLiveStatePort,
        authority: SemanticVerificationAuthority,
        policy: SemanticVerificationPolicy,
    ) -> None:
        self._port = port
        self._live_state = live_state
        self._authority = authority
        self._policy = policy

    async def verify(
        self,
        snapshot: SemanticVerificationContextSnapshot,
        *,
        blind_observation_id: str,
        relation_observation_id: str,
        semantic_observation_id: str,
        acceptance_id: str,
        created_at: datetime,
    ) -> SemanticVerificationRun:
        _ensure_eligible(snapshot, await self._live_state.current_state(snapshot))

        blind_request = build_blind_request(
            snapshot,
            created_at=created_at,
            policy=self._policy,
        )
        blind_result = await self._port.invoke(blind_request)
        _ensure_success(
            blind_descriptor(self._policy),
            blind_request,
            blind_result,
            "blind",
        )
        if blind_result.output is None:
            raise SemanticVerificationError(
                SemanticVerificationFailureCode.PROVIDER_FAILED,
                "blind Provider outputがありません",
            )
        blind_candidate = parse_blind_candidate(
            blind_result.output.value,
            observed_at=blind_result.completed_at,
        )
        _ensure_eligible(snapshot, await self._live_state.current_state(snapshot))
        blind = self._authority.commit_blind(
            blind_candidate,
            snapshot,
            observation_id=blind_observation_id,
            committed_at=blind_result.completed_at,
        )

        relation_request = build_relation_request(
            snapshot,
            blind,
            created_at=blind_result.completed_at,
            policy=self._policy,
        )
        relation_result = await self._port.invoke(relation_request)
        _ensure_success(
            relation_descriptor(self._policy),
            relation_request,
            relation_result,
            "relation",
        )
        if relation_result.output is None:
            raise SemanticVerificationError(
                SemanticVerificationFailureCode.PROVIDER_FAILED,
                "relation Provider outputがありません",
            )
        relation_candidate = parse_relation_candidate(
            relation_result.output.value,
            observed_at=relation_result.completed_at,
        )
        _ensure_eligible(snapshot, await self._live_state.current_state(snapshot))
        relation = self._authority.commit_relation(
            relation_candidate,
            snapshot,
            blind,
            observation_id=relation_observation_id,
            committed_at=relation_result.completed_at,
        )
        semantic_observation, acceptance = self._authority.reconcile(
            snapshot,
            blind,
            relation,
            observation_id=semantic_observation_id,
            acceptance_id=acceptance_id,
            committed_at=relation_result.completed_at,
        )
        return SemanticVerificationRun(
            blind_result,
            relation_result,
            blind,
            relation,
            semantic_observation,
            acceptance,
        )


def _ensure_success(
    descriptor: LLMRoleDescriptor,
    request: LLMRoleRequest,
    result: LLMRoleResult,
    stage: str,
) -> None:
    failure = validate_role_exchange(descriptor, request, result)
    if failure is not None:
        raise SemanticVerificationError(
            SemanticVerificationFailureCode.SCHEMA_INVALID,
            f"{stage} role exchange invalid: {failure.code.value}",
        )
    if result.status is not LLMRoleStatus.SUCCEEDED or result.output is None:
        raise SemanticVerificationError(
            SemanticVerificationFailureCode.PROVIDER_FAILED,
            f"{stage} Provider resultはcommitできません",
        )


def _ensure_eligible(
    snapshot: SemanticVerificationContextSnapshot,
    current: SemanticVerificationEligibilityView,
) -> None:
    if (
        current.semantic_plan_id != snapshot.semantic_plan.plan_id
        or current.utterance_id != snapshot.utterance.utterance_id
        or current.revisions != snapshot.revisions
    ):
        raise SemanticVerificationError(
            SemanticVerificationFailureCode.STALE,
            "Semantic Verification pairがstaleです",
        )
    if current.cancelled:
        raise SemanticVerificationError(
            SemanticVerificationFailureCode.CANCELLED,
            "Semantic Verification pairはcancelledです",
        )
    if current.superseded:
        raise SemanticVerificationError(
            SemanticVerificationFailureCode.SUPERSEDED,
            "Semantic Verification pairはsupersededです",
        )
    if not current.active:
        raise SemanticVerificationError(
            SemanticVerificationFailureCode.UNAVAILABLE,
            "Semantic Verification pairはactiveではありません",
        )


def _utterance_segments(
    snapshot: SemanticVerificationContextSnapshot,
) -> list[dict[str, str]]:
    return [
        {"segment_id": item.segment_id, "text": item.text}
        for item in snapshot.utterance.candidate.segments
    ]


E = TypeVar("E", bound=Enum)


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) for key in value
    ):
        raise ValueError(f"{name} はobjectでなければなりません")
    return cast(Mapping[str, object], value)


def _array(value: object, name: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{name} はarrayでなければなりません")
    return tuple(value)


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} は空でない文字列でなければなりません")
    return value


def _strings(value: object, name: str) -> tuple[str, ...]:
    return tuple(_string(item, name) for item in _array(value, name))


def _non_negative_int(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} は0以上の整数でなければなりません")
    return value


def _enum(enum_type: type[E], value: object, name: str) -> E:
    if not isinstance(value, str):
        raise ValueError(f"{name} は文字列でなければなりません")
    try:
        return enum_type(value)
    except ValueError as error:
        raise ValueError(f"{name} が不正です") from error


def _evidence(value: object) -> UtteranceEvidenceRef:
    item = _mapping(value, "evidence")
    if set(item) != {"segment_id", "quote", "occurrence_index"}:
        raise ValueError("evidence fieldがschemaと一致しません")
    return UtteranceEvidenceRef(
        _string(item["segment_id"], "segment_id"),
        _string(item["quote"], "quote"),
        _non_negative_int(item["occurrence_index"], "occurrence_index"),
    )


def _blind_unit(value: object) -> BlindSemanticUnit:
    item = _mapping(value, "blind unit")
    if set(item) != {"unit_id", "kind", "evidence_refs"}:
        raise ValueError("blind unit fieldがschemaと一致しません")
    return BlindSemanticUnit(
        _string(item["unit_id"], "unit_id"),
        _enum(BlindSemanticUnitKind, item["kind"], "kind"),
        tuple(
            _evidence(part)
            for part in _array(item["evidence_refs"], "evidence_refs")
        ),
    )


def _proposition_observation(value: object) -> PropositionSemanticObservation:
    item = _mapping(value, "proposition observation")
    required = {
        "proposition_id",
        "relation",
        "polarity_relation",
        "certainty_relation",
        "degree_relation",
        "execution_relation",
        "evidence_refs",
        "supporting_blind_unit_ids",
    }
    if set(item) != required:
        raise ValueError("proposition observation fieldがschemaと一致しません")
    return PropositionSemanticObservation(
        _string(item["proposition_id"], "proposition_id"),
        _enum(PropositionRelation, item["relation"], "relation"),
        _enum(PolarityRelation, item["polarity_relation"], "polarity_relation"),
        _enum(
            CertaintyRelation,
            item["certainty_relation"],
            "certainty_relation",
        ),
        _enum(DegreeRelation, item["degree_relation"], "degree_relation"),
        _enum(
            ExecutionRelation,
            item["execution_relation"],
            "execution_relation",
        ),
        tuple(
            _evidence(part)
            for part in _array(item["evidence_refs"], "evidence_refs")
        ),
        _strings(
            item["supporting_blind_unit_ids"],
            "supporting_blind_unit_ids",
        ),
    )


def _accounting(value: object) -> BlindUnitAccounting:
    item = _mapping(value, "blind unit accounting")
    required = {"blind_unit_id", "relation", "proposition_ids", "evidence_refs"}
    if set(item) != required:
        raise ValueError("blind unit accounting fieldがschemaと一致しません")
    return BlindUnitAccounting(
        _string(item["blind_unit_id"], "blind_unit_id"),
        _enum(BlindUnitAccountingRelation, item["relation"], "relation"),
        _strings(item["proposition_ids"], "proposition_ids"),
        tuple(
            _evidence(part)
            for part in _array(item["evidence_refs"], "evidence_refs")
        ),
    )
