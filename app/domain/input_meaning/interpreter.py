from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, cast

from app.domain.contracts.common import JsonValue, freeze_json, require_revision
from app.domain.input_gateway import InputModality, NormalizedInputEvent
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

from .contracts import ReferenceContext, StructuredInputMeaning, meaning_from_json

INPUT_SCHEMA = "yura.input-meaning.request.v1"
OUTPUT_SCHEMA = "yura.input-meaning.result.v1"
ROLE_ID = "input_meaning"


@dataclass(frozen=True, slots=True)
class InputMeaningPolicy:
    execution: LLMExecutionPolicy
    minimum_confidence: float = 0.65

    def __post_init__(self) -> None:
        if (
            type(self.minimum_confidence) not in (int, float)
            or not 0 <= self.minimum_confidence <= 1
        ):
            raise ValueError("minimum_confidence must be between 0 and 1")


class InputMeaningLiveContextPort(Protocol):
    """Input Meaning commit直前のsource context世代を読み取る境界。"""

    async def current_source_context_revision(self) -> int: ...


def descriptor(policy: InputMeaningPolicy) -> LLMRoleDescriptor:
    return LLMRoleDescriptor(
        ROLE_ID,
        "外部自然言語が伝えた意味を構造化する",
        INPUT_SCHEMA,
        OUTPUT_SCHEMA,
        "input_meaning_candidate",
        LLMActivationPolicy.REQUIRED,
        LLMFailurePolicy.FAIL_CLOSED,
        policy.execution,
    )


def build_request(
    event: NormalizedInputEvent,
    context: ReferenceContext,
    *,
    request_id: str,
    trace_id: str,
    created_at: datetime,
    policy: InputMeaningPolicy,
) -> LLMRoleRequest:
    if event.modality not in (InputModality.TEXT, InputModality.SPEECH):
        raise ValueError("input meaning accepts only text or speech modality")
    payload = event.envelope.payload
    expected_prefix = f"input.{event.modality.value}."
    if not event.envelope.event_type.startswith(expected_prefix):
        raise ValueError("input event_type does not match wrapper modality")
    content = payload.get("content") if isinstance(payload, Mapping) else None
    payload_modality = payload.get("modality") if isinstance(payload, Mapping) else None
    payload_source = payload.get("source") if isinstance(payload, Mapping) else None
    if payload_modality != event.modality.value:
        raise ValueError("input payload modality does not match wrapper modality")
    if (
        not isinstance(payload_source, Mapping)
        or payload_source.get("source_id") != event.source.source_id
        or event.envelope.source != event.source.source_id
    ):
        raise ValueError("input source identity is inconsistent")
    if not isinstance(content, Mapping) or set(content) != {"text"}:
        raise ValueError("natural language content must contain only text")
    text = content.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be a non-empty string")
    if context.source_context_revision != event.envelope.revisions.source_context_revision:
        raise ValueError("reference context revision must match input event")
    request_value = cast(
        JsonValue,
        {
            "text": text,
            "modality": event.modality.value,
            "reference_context": context.to_dict(),
        },
    )
    structured_input = StructuredPayload(INPUT_SCHEMA, request_value)
    return LLMRoleRequest(
        request_id,
        ROLE_ID,
        structured_input,
        (event.envelope.event_id,),
        event.envelope.revisions,
        (),
        LLMPriority.FOREGROUND,
        LLMInterruptibility.INTERRUPTIBLE,
        LLMStalePolicy.REJECT,
        policy.execution,
        created_at,
        trace_id,
    )


def commit_result(
    request: LLMRoleRequest,
    result: LLMRoleResult,
    *,
    reference_context: ReferenceContext,
    current_source_context_revision: int,
    policy: InputMeaningPolicy,
) -> StructuredInputMeaning:
    require_revision(current_source_context_revision, "current_source_context_revision")
    failure = validate_role_exchange(descriptor(policy), request, result)
    if failure is not None:
        raise ValueError(failure.code.value)
    if result.status is not LLMRoleStatus.SUCCEEDED or result.output is None:
        raise ValueError("input meaning result is not committable")
    if request.revisions.source_context_revision != current_source_context_revision:
        raise ValueError("input meaning result is stale")
    request_value = request.input.value
    if not isinstance(request_value, Mapping):
        raise ValueError("input meaning request payload is invalid")
    encoded_context = request_value.get("reference_context")
    if encoded_context != freeze_json(reference_context.to_dict()):
        raise ValueError("reference context does not match request snapshot")
    meaning = meaning_from_json(
        result.output.value,
        source_event_id=request.source_event_ids[0],
        source_context_revision=current_source_context_revision,
        minimum_confidence=policy.minimum_confidence,
    )
    allowed_refs = {
        value
        for item in reference_context.entries
        for value in (item.reference_id, item.subject_ref)
    }
    if any(
        item.resolved_ref is not None and item.resolved_ref not in allowed_refs
        for item in meaning.references
    ):
        raise ValueError("resolved reference is outside bounded reference context")
    return meaning


class InputMeaningInterpreter:
    def __init__(
        self,
        port: LLMRolePort,
        live_context: InputMeaningLiveContextPort,
        policy: InputMeaningPolicy,
    ) -> None:
        self._port = port
        self._live_context = live_context
        self._policy = policy

    async def interpret(
        self,
        event: NormalizedInputEvent,
        context: ReferenceContext,
        *,
        request_id: str,
        trace_id: str,
        created_at: datetime,
    ) -> StructuredInputMeaning:
        request = build_request(
            event,
            context,
            request_id=request_id,
            trace_id=trace_id,
            created_at=created_at,
            policy=self._policy,
        )
        result = await self._port.invoke(request)
        current_source_context_revision = await self._live_context.current_source_context_revision()
        return commit_result(
            request,
            result,
            reference_context=context,
            current_source_context_revision=current_source_context_revision,
            policy=self._policy,
        )
