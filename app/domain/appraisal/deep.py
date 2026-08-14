from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from app.domain.contracts import EventEnvelope
from app.domain.contracts.common import JsonValue, freeze_json, require_identifier
from app.domain.input_meaning import StructuredInputMeaning
from app.domain.llm import (
    LLMActivationPolicy,
    LLMExecutionPolicy,
    LLMFailurePolicy,
    LLMInterruptibility,
    LLMPriority,
    LLMRoleDescriptor,
    LLMRoleRequest,
    LLMRoleResult,
    LLMRoleStatus,
    LLMStalePolicy,
    StructuredPayload,
    validate_role_exchange,
)
from app.usecases.ports.llm import LLMRolePort

from .contracts import (
    AppraisalCandidate,
    AppraisalDimension,
    AppraisalDimensionKind,
    AppraisalPath,
    FacetRef,
    InternalStateSnapshot,
    StateDeltaProposal,
    StateFacetKind,
)

ROLE_ID = "subjective_appraisal"
INPUT_SCHEMA = "yura.subjective-appraisal.request.v1"
OUTPUT_SCHEMA = "yura.subjective-appraisal.candidate.v1"


@dataclass(frozen=True, slots=True)
class DeepAppraisalContext:
    context_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.context_refs, (list, tuple)):
            raise ValueError("context_refs must be an array")
        refs = tuple(self.context_refs)
        if any(not isinstance(item, str) or not item.strip() for item in refs):
            raise ValueError("context_refs must contain non-empty strings")
        if len(refs) != len(set(refs)):
            raise ValueError("context_refs must be unique")
        object.__setattr__(self, "context_refs", refs)

    def to_dict(self) -> dict[str, object]:
        return {"context_refs": list(self.context_refs)}


@dataclass(frozen=True, slots=True)
class DeepAppraisalPolicy:
    execution: LLMExecutionPolicy

    def __post_init__(self) -> None:
        if not isinstance(self.execution, LLMExecutionPolicy):
            raise ValueError("execution must be LLMExecutionPolicy")


def descriptor(policy: DeepAppraisalPolicy) -> LLMRoleDescriptor:
    return LLMRoleDescriptor(
        ROLE_ID,
        "現在のゆらにとっての主観的意味を候補化する",
        INPUT_SCHEMA,
        OUTPUT_SCHEMA,
        "appraisal_candidate",
        LLMActivationPolicy.OPTIONAL,
        LLMFailurePolicy.SKIP_OPTIONAL,
        policy.execution,
    )


def build_deep_request(
    event: EventEnvelope,
    meaning: StructuredInputMeaning | None,
    snapshot: InternalStateSnapshot,
    context: DeepAppraisalContext,
    *,
    request_id: str,
    trace_id: str,
    created_at: datetime,
    policy: DeepAppraisalPolicy,
) -> LLMRoleRequest:
    if event.revisions.source_context_revision != snapshot.source_context_revision:
        raise ValueError("event and state context revisions must match")
    if meaning is not None:
        if meaning.source_event_id != event.event_id:
            raise ValueError("meaning source event must match appraisal event")
        if meaning.source_context_revision != event.revisions.source_context_revision:
            raise ValueError("meaning context revision must match appraisal event")
    event_view = _appraisal_event_view(event, meaning)
    value = cast(
        JsonValue,
        {
            "event": event_view,
            "meaning": None if meaning is None else meaning.to_dict(),
            "state": snapshot.to_dict(),
            "context": context.to_dict(),
        },
    )
    return LLMRoleRequest(
        request_id,
        ROLE_ID,
        StructuredPayload(INPUT_SCHEMA, value),
        (event.event_id,),
        event.revisions,
        (),
        LLMPriority.NORMAL,
        LLMInterruptibility.INTERRUPTIBLE,
        LLMStalePolicy.REJECT,
        policy.execution,
        created_at,
        trace_id,
    )


def commit_deep_result(
    request: LLMRoleRequest,
    result: LLMRoleResult,
    *,
    event: EventEnvelope,
    snapshot: InternalStateSnapshot,
    context: DeepAppraisalContext,
    current_source_context_revision: int,
    current_state_revision: int,
    policy: DeepAppraisalPolicy,
) -> AppraisalCandidate:
    failure = validate_role_exchange(descriptor(policy), request, result)
    if failure is not None:
        raise ValueError(failure.code.value)
    if result.status is not LLMRoleStatus.SUCCEEDED or result.output is None:
        raise ValueError("deep appraisal result is not committable")
    if current_source_context_revision != request.revisions.source_context_revision:
        raise ValueError("deep appraisal result has stale source context")
    if current_state_revision != snapshot.revision:
        raise ValueError("deep appraisal result has stale state revision")
    request_value = request.input.value
    if not isinstance(request_value, Mapping):
        raise ValueError("deep appraisal request payload is invalid")
    encoded_meaning = request_value.get("meaning")
    meaning_was_supplied = encoded_meaning is not None
    if request_value.get("event") != freeze_json(
        _appraisal_event_view(
            event, cast(object, encoded_meaning) if meaning_was_supplied else None
        )
    ):
        raise ValueError("appraisal event does not match request snapshot")
    if request_value.get("state") != freeze_json(snapshot.to_dict()):
        raise ValueError("appraisal state does not match request snapshot")
    if request_value.get("context") != freeze_json(context.to_dict()):
        raise ValueError("appraisal context does not match request snapshot")
    return _candidate_from_json(
        result.output.value,
        source_event_id=event.event_id,
        source_context_revision=current_source_context_revision,
        base_state_revision=current_state_revision,
        allowed_refs={
            event.event_id,
            *context.context_refs,
            *(item.ref.target_ref for item in snapshot.facets if item.ref.target_ref is not None),
        },
        created_at=result.completed_at,
    )


class DeepAppraisalInterpreter:
    def __init__(self, port: LLMRolePort, policy: DeepAppraisalPolicy) -> None:
        self._port = port
        self._policy = policy

    async def appraise(
        self,
        event: EventEnvelope,
        meaning: StructuredInputMeaning | None,
        snapshot: InternalStateSnapshot,
        context: DeepAppraisalContext,
        *,
        request_id: str,
        trace_id: str,
        created_at: datetime,
        current_source_context_revision: int,
        current_state_revision: int,
    ) -> AppraisalCandidate:
        request = build_deep_request(
            event,
            meaning,
            snapshot,
            context,
            request_id=request_id,
            trace_id=trace_id,
            created_at=created_at,
            policy=self._policy,
        )
        result = await self._port.invoke(request)
        return commit_deep_result(
            request,
            result,
            event=event,
            snapshot=snapshot,
            context=context,
            current_source_context_revision=current_source_context_revision,
            current_state_revision=current_state_revision,
            policy=self._policy,
        )


def _candidate_from_json(
    value: object,
    *,
    source_event_id: str,
    source_context_revision: int,
    base_state_revision: int,
    allowed_refs: set[str],
    created_at: datetime,
) -> AppraisalCandidate:
    required = {"candidate_id", "dimensions", "proposals", "salience", "relevance", "evidence_refs"}
    if not isinstance(value, Mapping) or set(value) != required:
        raise ValueError("deep appraisal output fields do not match schema")
    candidate_id = value["candidate_id"]
    require_identifier(candidate_id, "candidate_id")
    dimensions_raw, proposals_raw = value["dimensions"], value["proposals"]
    if not isinstance(dimensions_raw, tuple) or not isinstance(proposals_raw, tuple):
        raise ValueError("dimensions and proposals must be arrays")
    evidence_refs = _strings(value["evidence_refs"], "evidence_refs")
    dimensions = tuple(_dimension(item) for item in dimensions_raw)
    proposals = tuple(_proposal(item) for item in proposals_raw)
    used_refs = set(evidence_refs)
    used_refs.update(ref for item in proposals for ref in item.cause_refs)
    if not used_refs <= allowed_refs:
        raise ValueError("appraisal evidence is outside bounded context")
    target_refs = {item.target_ref for item in dimensions if item.target_ref is not None}
    target_refs.update(
        item.facet_ref.target_ref for item in proposals if item.facet_ref.target_ref is not None
    )
    if not target_refs <= allowed_refs:
        raise ValueError("appraisal target is outside bounded context")
    return AppraisalCandidate(
        candidate_id,
        (source_event_id,),
        source_context_revision,
        base_state_revision,
        AppraisalPath.DEEP_LLM,
        dimensions,
        proposals,
        value["salience"],
        value["relevance"],
        evidence_refs,
        created_at,
    )


def _appraisal_event_view(event: EventEnvelope, meaning: object | None) -> dict[str, object]:
    value = event.to_dict()
    is_natural_language = event.event_type.startswith(("input.text.", "input.speech."))
    if is_natural_language:
        if meaning is None:
            raise ValueError("natural language appraisal requires StructuredInputMeaning")
        value.pop("payload")
    return value


def _dimension(value: object) -> AppraisalDimension:
    if not isinstance(value, Mapping) or set(value) != {"kind", "value", "target_ref"}:
        raise ValueError("appraisal dimension fields do not match schema")
    return AppraisalDimension(
        AppraisalDimensionKind(value["kind"]), value["value"], value["target_ref"]
    )


def _proposal(value: object) -> StateDeltaProposal:
    required = {"facet_kind", "state_key", "target_ref", "delta", "confidence", "cause_refs"}
    if not isinstance(value, Mapping) or set(value) != required:
        raise ValueError("state delta fields do not match schema")
    return StateDeltaProposal(
        FacetRef(StateFacetKind(value["facet_kind"]), value["state_key"], value["target_ref"]),
        value["delta"],
        value["confidence"],
        _strings(value["cause_refs"], "cause_refs"),
    )


def _strings(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be an array of strings")
    return value
