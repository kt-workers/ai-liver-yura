"""Reflectionの世代別wireと、既存LLMRolePortへのproduction接続。"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import cast

from jsonschema import ValidationError, validate

from app.domain.contracts.common import (
    JsonValue,
    RevisionVector,
    freeze_json,
    require_aware,
    thaw_json,
    utc_instant,
)
from app.domain.contracts.semantic_subject import SemanticSubjectIdentity, SemanticSubjectKind
from app.domain.llm import (
    LLMActivationPolicy,
    LLMExecutionPolicy,
    LLMFailureCode,
    LLMFailurePolicy,
    LLMInterruptibility,
    LLMPriority,
    LLMRoleDescriptor,
    LLMRoleRequest,
    LLMRoleStatus,
    LLMStalePolicy,
    StructuredPayload,
    validate_role_exchange,
)
from app.domain.memory.contracts import (
    MemoryAssertionSemantics,
    MemoryContent,
    MemoryFreshnessState,
    MemoryKind,
    MemoryRelationKind,
    MemoryTemporalState,
)
from app.usecases.ports.llm import LLMRolePort

from .contracts import (
    MemoryCandidateProposal,
    ReflectionContextSnapshot,
    ReflectionPersistenceHint,
    ReflectionRelationHint,
    ReflectionRoleFailure,
    ReflectionSupportObservation,
    ReflectionSupportRelation,
    context_to_wire_v2,
    subject_identity_is_grounded,
)
from .operational import (
    ReflectionOperationalError,
    ReflectionOperationalFailureCode,
    ReflectionOperationalPolicy,
    validate_reflection_context_bounds,
    validate_reflection_proposals_bounds,
    validate_reflection_support_bounds,
)
from .schemas import (
    proposal_output_schema,
    proposal_output_schema_v2,
    proposal_output_schema_v3,
    support_output_schema,
)

PROPOSAL_ROLE_ID = "memory_reflection"
PROPOSAL_INPUT_SCHEMA_V1 = "memory.reflection.context.v1"
PROPOSAL_INPUT_SCHEMA_V2 = "memory.reflection.context.v2"
PROPOSAL_INPUT_SCHEMA = PROPOSAL_INPUT_SCHEMA_V2
PROPOSAL_OUTPUT_SCHEMA_V1 = "memory.reflection.candidates.v1"
PROPOSAL_OUTPUT_SCHEMA_V2 = "memory.reflection.candidates.v2"
PROPOSAL_OUTPUT_SCHEMA = "memory.reflection.candidates.v3"
SUPPORT_ROLE_ID = "memory_reflection_support"
SUPPORT_INPUT_SCHEMA_V1 = "memory.reflection.support.v1"
SUPPORT_INPUT_SCHEMA_V2 = "memory.reflection.support.v2"
SUPPORT_INPUT_SCHEMA = "memory.reflection.support.v3"
SUPPORT_OUTPUT_SCHEMA = "memory.reflection.support.observation.v1"


@dataclass(frozen=True, slots=True)
class ReflectionLLMRolePolicy:
    proposal_execution: LLMExecutionPolicy
    support_execution: LLMExecutionPolicy
    operational: ReflectionOperationalPolicy

    def __post_init__(self) -> None:
        if (
            not isinstance(self.proposal_execution, LLMExecutionPolicy)
            or not isinstance(self.support_execution, LLMExecutionPolicy)
            or not isinstance(self.operational, ReflectionOperationalPolicy)
        ):
            raise ValueError("Reflectionのexecution/operational policyを明示してください")


class ReflectionLLMError(ReflectionRoleFailure):
    """production Portの失敗を共通typed境界へ渡す。"""


def _operational_failure(error: ReflectionOperationalError) -> ReflectionLLMError:
    return ReflectionLLMError(
        LLMFailureCode.STALE
        if error.code is ReflectionOperationalFailureCode.POLICY_STALE
        else LLMFailureCode.POLICY_VIOLATION
    )


def proposal_descriptor(policy: ReflectionLLMRolePolicy) -> LLMRoleDescriptor:
    return LLMRoleDescriptor(
        PROPOSAL_ROLE_ID,
        "frozen根拠からMemory候補だけを提案する",
        PROPOSAL_INPUT_SCHEMA,
        PROPOSAL_OUTPUT_SCHEMA,
        "memory_candidate_proposal_only",
        LLMActivationPolicy.BACKGROUND,
        LLMFailurePolicy.FAIL_CLOSED,
        policy.proposal_execution,
    )


def support_descriptor(policy: ReflectionLLMRolePolicy) -> LLMRoleDescriptor:
    return LLMRoleDescriptor(
        SUPPORT_ROLE_ID,
        "frozen根拠に対するMemory候補のsupportだけを観測する",
        SUPPORT_INPUT_SCHEMA,
        SUPPORT_OUTPUT_SCHEMA,
        "memory_reflection_support_observation_only",
        LLMActivationPolicy.BACKGROUND,
        LLMFailurePolicy.FAIL_CLOSED,
        policy.support_execution,
    )


def _canonical_json(value: JsonValue) -> str:
    text = json.dumps(
        thaw_json(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    text.encode("utf-8")
    return text


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("value_jsonのobject keyが重複しています")
        result[key] = value
    return result


def _invalid_constant(value: str) -> object:
    raise ValueError("value_jsonに非有限値は使えません")


def _decode_value(text: str) -> JsonValue:
    decoded = freeze_json(
        json.loads(text, object_pairs_hook=_pairs, parse_constant=_invalid_constant)
    )
    _canonical_json(decoded)
    return decoded


def proposal_to_wire(proposal: MemoryCandidateProposal) -> dict[str, object]:
    if proposal.subject_identity is not None:
        raise ValueError("旧wireに明示subject_identityを落として搬送できません")
    if proposal.assertion_semantics is not None:
        raise ValueError("V1 wireに明示semanticsを落として搬送できません")
    if proposal.deterministic_capture:
        raise ValueError("trusted deterministic captureはopen-ended V1の対象外です")
    content, temporal = proposal.content, proposal.temporal
    return {
        "proposal_id": proposal.proposal_id,
        "proposed_kind": proposal.proposed_kind.value,
        "content": {
            "predicate": content.predicate,
            "value_json": _canonical_json(content.value),
            "subject_ref": content.subject_ref,
            "temporal_scope_ref": content.temporal_scope_ref,
            "qualifiers": list(content.qualifiers),
        },
        "source_refs": list(proposal.source_refs),
        "confidence_hint": proposal.confidence_hint,
        "importance_hint": proposal.importance_hint,
        "persistence_hint": proposal.persistence_hint.value,
        "novelty_hint": proposal.novelty_hint,
        "temporal": {
            "freshness": temporal.freshness.value,
            "valid_from": None if temporal.valid_from is None else temporal.valid_from.isoformat(),
            "valid_until": None
            if temporal.valid_until is None
            else temporal.valid_until.isoformat(),
            "observed_at": None
            if temporal.observed_at is None
            else temporal.observed_at.isoformat(),
        },
        "suggested_related_memory_ids": list(proposal.suggested_related_memory_ids),
        "relation_hints": [
            {
                "related_memory_id": h.related_memory_id,
                "related_memory_revision": h.related_memory_revision,
                "relation_kind": h.relation_kind.value,
                "evidence_refs": list(h.evidence_refs),
                "confidence": h.confidence,
            }
            for h in proposal.relation_hints
        ],
        "rationale_evidence_refs": list(proposal.rationale_evidence_refs),
    }


def _object(value: object) -> Mapping[str, object]:
    return cast(Mapping[str, object], value)


def _array(value: object) -> tuple[object, ...]:
    return tuple(cast(list[object], value))


def _refs(value: object) -> tuple[str, ...]:
    return tuple(cast(list[str], value))


def _timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    result = datetime.fromisoformat(cast(str, value).replace("Z", "+00:00"))
    require_aware(result, "timestamp")
    return result


def _validated_wire(value: object, schema: dict[str, object]) -> Mapping[str, object]:
    normalized = thaw_json(freeze_json(value))
    validate(normalized, schema)
    return _object(normalized)


def _parse_proposal(item: Mapping[str, object]) -> MemoryCandidateProposal:
    content = _object(item["content"])
    temporal = _object(item["temporal"])
    hints = tuple(_object(h) for h in _array(item["relation_hints"]))
    return MemoryCandidateProposal(
        cast(str, item["proposal_id"]),
        MemoryKind(item["proposed_kind"]),
        MemoryContent(
            cast(str, content["predicate"]),
            _decode_value(cast(str, content["value_json"])),
            cast(str | None, content["subject_ref"]),
            cast(str | None, content["temporal_scope_ref"]),
            _refs(content["qualifiers"]),
        ),
        _refs(item["source_refs"]),
        cast(float, item["confidence_hint"]),
        cast(float, item["importance_hint"]),
        ReflectionPersistenceHint(item["persistence_hint"]),
        cast(float, item["novelty_hint"]),
        MemoryTemporalState(
            MemoryFreshnessState(temporal["freshness"]),
            _timestamp(temporal["valid_from"]),
            _timestamp(temporal["valid_until"]),
            _timestamp(temporal["observed_at"]),
        ),
        _refs(item["suggested_related_memory_ids"]),
        tuple(
            ReflectionRelationHint(
                cast(str, h["related_memory_id"]),
                cast(int, h["related_memory_revision"]),
                MemoryRelationKind(h["relation_kind"]),
                _refs(h["evidence_refs"]),
                cast(float, h["confidence"]),
            )
            for h in hints
        ),
        _refs(item["rationale_evidence_refs"]),
        deterministic_capture=False,
    )


def _validate_provenance(
    context: ReflectionContextSnapshot, proposal: MemoryCandidateProposal
) -> None:
    sources = {s.source_ref for s in context.primary_sources}
    memories = {m.memory_id: m.revision for m in context.related_memory_view}
    if (
        not subject_identity_is_grounded(context, proposal.subject_identity, proposal.source_refs)
        or not set(proposal.source_refs).issubset(sources)
        or not set(proposal.rationale_evidence_refs).issubset(sources)
        or not set(proposal.suggested_related_memory_ids).issubset(memories)
        or any(
            memories.get(h.related_memory_id) != h.related_memory_revision
            or h.related_memory_id not in proposal.suggested_related_memory_ids
            or not set(h.evidence_refs).issubset(sources)
            for h in proposal.relation_hints
        )
    ):
        raise ReflectionLLMError(LLMFailureCode.POLICY_VIOLATION)


def _parse_proposals(
    value: object,
    context: ReflectionContextSnapshot,
    policy: ReflectionOperationalPolicy,
    *,
    version: int,
) -> tuple[MemoryCandidateProposal, ...]:
    try:
        validate_reflection_context_bounds(context, policy, context_v2=version == 3)
        schema = {
            1: proposal_output_schema,
            2: proposal_output_schema_v2,
            3: proposal_output_schema_v3,
        }[version]
        item = _validated_wire(value, schema())
        proposals = tuple(_parse_proposal(_object(p)) for p in _array(item["proposals"]))
        if version >= 2:
            proposals = tuple(
                replace(
                    proposal,
                    assertion_semantics=(
                        None
                        if _object(raw)["assertion_semantics"] is None
                        else MemoryAssertionSemantics.from_dict(_object(raw)["assertion_semantics"])
                    ),
                )
                for proposal, raw in zip(proposals, _array(item["proposals"]), strict=True)
            )
        if version == 3:
            proposals = tuple(
                replace(
                    proposal,
                    subject_identity=(
                        None
                        if _object(raw)["subject_identity"] is None
                        else SemanticSubjectIdentity(
                            SemanticSubjectKind(_object(_object(raw)["subject_identity"])["kind"]),
                            cast(str, _object(_object(raw)["subject_identity"])["subject_ref"]),
                        )
                    ),
                )
                for proposal, raw in zip(proposals, _array(item["proposals"]), strict=True)
            )
        validate_reflection_proposals_bounds(proposals, policy)
        for proposal in proposals:
            _validate_provenance(context, proposal)
        return proposals
    except ReflectionOperationalError as error:
        raise _operational_failure(error) from None
    except (ValueError, ValidationError, RecursionError):
        raise ReflectionLLMError(LLMFailureCode.SCHEMA_INVALID) from None


def parse_support(
    value: object,
    context: ReflectionContextSnapshot,
    proposal: MemoryCandidateProposal,
    policy: ReflectionOperationalPolicy,
    *,
    context_v2: bool = False,
) -> ReflectionSupportObservation:
    try:
        validate_reflection_context_bounds(context, policy, context_v2=context_v2)
        _validate_provenance(context, proposal)
        item = _validated_wire(value, support_output_schema())
        result = ReflectionSupportObservation(
            cast(str, item["proposal_id"]),
            ReflectionSupportRelation(item["support_relation"]),
            _refs(item["evidence_refs"]),
            _refs(item["unsupported_content_refs"]),
            _refs(item["contradiction_refs"]),
            cast(float, item["confidence"]),
        )
        validate_reflection_support_bounds(result, policy)
        sources = {s.source_ref for s in context.primary_sources}
        if (
            (
                result.support_relation is ReflectionSupportRelation.SUPPORTED
                and not subject_identity_is_grounded(
                    context, proposal.subject_identity, result.evidence_refs
                )
            )
            or result.proposal_id != proposal.proposal_id
            or not set(
                (
                    *result.evidence_refs,
                    *result.unsupported_content_refs,
                    *result.contradiction_refs,
                )
            ).issubset(sources)
            or not set(result.evidence_refs).issubset(proposal.source_refs)
        ):
            raise ReflectionLLMError(LLMFailureCode.POLICY_VIOLATION)
        return result
    except ReflectionOperationalError as error:
        raise _operational_failure(error) from None
    except (ValueError, ValidationError, RecursionError):
        raise ReflectionLLMError(LLMFailureCode.SCHEMA_INVALID) from None


def _request(
    context: ReflectionContextSnapshot,
    descriptor: LLMRoleDescriptor,
    payload: dict[str, object],
    request_id: str,
    created_at: datetime,
) -> LLMRoleRequest:
    require_aware(created_at, "created_at")
    if utc_instant(created_at) < utc_instant(context.captured_at):
        raise ValueError("request時刻はcontextの取得より前にできません")
    return LLMRoleRequest(
        request_id,
        descriptor.role_id,
        StructuredPayload(descriptor.input_schema_id, freeze_json(payload)),
        (),
        RevisionVector(context.source_context_revision),
        (),
        LLMPriority.BACKGROUND,
        LLMInterruptibility.INTERRUPTIBLE
        if context.trigger.interruptible
        else LLMInterruptibility.NON_INTERRUPTIBLE,
        LLMStalePolicy.REVALIDATE,
        descriptor.default_execution_policy,
        created_at,
        context.trace_id,
    )


def build_proposal_request(
    context: ReflectionContextSnapshot, *, created_at: datetime, policy: ReflectionLLMRolePolicy
) -> LLMRoleRequest:
    validate_reflection_context_bounds(context, policy.operational, context_v2=True)
    return _request(
        context,
        proposal_descriptor(policy),
        context_to_wire_v2(context),
        f"{context.reflection_id}:proposal",
        created_at,
    )


def build_support_request(
    context: ReflectionContextSnapshot,
    proposal: MemoryCandidateProposal,
    *,
    created_at: datetime,
    policy: ReflectionLLMRolePolicy,
) -> LLMRoleRequest:
    validate_reflection_context_bounds(context, policy.operational, context_v2=True)
    validate_reflection_proposals_bounds((proposal,), policy.operational)
    _validate_provenance(context, proposal)
    return _request(
        context,
        support_descriptor(policy),
        {"context": context_to_wire_v2(context), "proposal": proposal_to_wire_v3(proposal)},
        f"{context.reflection_id}:support:{proposal.proposal_id}",
        created_at,
    )


async def _invoke(
    port: LLMRolePort, request: LLMRoleRequest, descriptor: LLMRoleDescriptor
) -> JsonValue:
    result = await port.invoke(request)
    failure = validate_role_exchange(descriptor, request, result)
    if failure is not None:
        raise ReflectionLLMError(failure.code)
    if result.status is not LLMRoleStatus.SUCCEEDED or result.output is None:
        assert result.failure is not None
        raise ReflectionLLMError(result.failure.code)
    return result.output.value


class LLMReflectionProposalPort:
    def __init__(
        self, port: LLMRolePort, policy: ReflectionLLMRolePolicy, *, now: Callable[[], datetime]
    ) -> None:
        self._port, self._policy, self._now = port, policy, now

    async def propose(
        self, context: ReflectionContextSnapshot
    ) -> tuple[MemoryCandidateProposal, ...]:
        try:
            request = build_proposal_request(context, created_at=self._now(), policy=self._policy)
        except ReflectionOperationalError as error:
            raise _operational_failure(error) from None
        except (ValueError, RecursionError) as error:
            raise ReflectionLLMError(LLMFailureCode.POLICY_VIOLATION) from error
        value = await _invoke(self._port, request, proposal_descriptor(self._policy))
        return parse_proposals_v3(value, context, self._policy.operational)


class LLMReflectionSupportPort:
    def __init__(
        self, port: LLMRolePort, policy: ReflectionLLMRolePolicy, *, now: Callable[[], datetime]
    ) -> None:
        self._port, self._policy, self._now = port, policy, now

    async def observe(
        self, context: ReflectionContextSnapshot, proposal: MemoryCandidateProposal
    ) -> ReflectionSupportObservation:
        try:
            request = build_support_request(
                context, proposal, created_at=self._now(), policy=self._policy
            )
        except ReflectionOperationalError as error:
            raise _operational_failure(error) from None
        except (ValueError, RecursionError) as error:
            raise ReflectionLLMError(LLMFailureCode.POLICY_VIOLATION) from error
        value = await _invoke(self._port, request, support_descriptor(self._policy))
        return parse_support(value, context, proposal, self._policy.operational, context_v2=True)


proposal_to_wire_v1 = proposal_to_wire


def proposal_to_wire_v2(proposal: MemoryCandidateProposal) -> dict[str, object]:
    wire = proposal_to_wire_v1(replace(proposal, assertion_semantics=None))
    wire["assertion_semantics"] = (
        None if proposal.assertion_semantics is None else proposal.assertion_semantics.to_dict()
    )
    return wire


def parse_proposals_v1(
    value: object, context: ReflectionContextSnapshot, policy: ReflectionOperationalPolicy
) -> tuple[MemoryCandidateProposal, ...]:
    return _parse_proposals(value, context, policy, version=1)


def parse_proposals_v2(
    value: object, context: ReflectionContextSnapshot, policy: ReflectionOperationalPolicy
) -> tuple[MemoryCandidateProposal, ...]:
    return _parse_proposals(value, context, policy, version=2)


# 既存呼出しのV1 wire互換性を保持する。
parse_proposals = parse_proposals_v1


def proposal_to_wire_v3(proposal: MemoryCandidateProposal) -> dict[str, object]:
    wire = proposal_to_wire_v2(replace(proposal, subject_identity=None))
    identity = proposal.subject_identity
    wire["subject_identity"] = (
        None
        if identity is None
        else {
            "kind": identity.kind.value,
            "subject_ref": identity.subject_ref,
        }
    )
    return wire


def parse_proposals_v3(
    value: object, context: ReflectionContextSnapshot, policy: ReflectionOperationalPolicy
) -> tuple[MemoryCandidateProposal, ...]:
    return _parse_proposals(value, context, policy, version=3)


def build_proposal_request_v1(
    context: ReflectionContextSnapshot, *, created_at: datetime, policy: ReflectionLLMRolePolicy
) -> LLMRoleRequest:
    """凍結したV1 inputを互換呼出しへ明示提供する。"""
    validate_reflection_context_bounds(context, policy.operational)
    descriptor = replace(
        proposal_descriptor(policy),
        input_schema_id=PROPOSAL_INPUT_SCHEMA_V1,
        output_schema_id=PROPOSAL_OUTPUT_SCHEMA_V1,
    )
    return _request(
        context, descriptor, context.to_dict(), f"{context.reflection_id}:proposal", created_at
    )


def _build_legacy_support_request(
    context: ReflectionContextSnapshot,
    proposal: MemoryCandidateProposal,
    *,
    created_at: datetime,
    policy: ReflectionLLMRolePolicy,
    v2: bool,
) -> LLMRoleRequest:
    validate_reflection_context_bounds(context, policy.operational)
    validate_reflection_proposals_bounds((proposal,), policy.operational)
    _validate_provenance(context, proposal)
    descriptor = replace(
        support_descriptor(policy),
        input_schema_id=(SUPPORT_INPUT_SCHEMA_V2 if v2 else SUPPORT_INPUT_SCHEMA_V1),
    )
    wire = proposal_to_wire_v2(proposal) if v2 else proposal_to_wire_v1(proposal)
    return _request(
        context,
        descriptor,
        {"context": context.to_dict(), "proposal": wire},
        f"{context.reflection_id}:support:{proposal.proposal_id}",
        created_at,
    )


def build_support_request_v1(
    context: ReflectionContextSnapshot,
    proposal: MemoryCandidateProposal,
    *,
    created_at: datetime,
    policy: ReflectionLLMRolePolicy,
) -> LLMRoleRequest:
    return _build_legacy_support_request(
        context, proposal, created_at=created_at, policy=policy, v2=False
    )


def build_support_request_v2(
    context: ReflectionContextSnapshot,
    proposal: MemoryCandidateProposal,
    *,
    created_at: datetime,
    policy: ReflectionLLMRolePolicy,
) -> LLMRoleRequest:
    return _build_legacy_support_request(
        context, proposal, created_at=created_at, policy=policy, v2=True
    )
