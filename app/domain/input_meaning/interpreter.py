from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from app.domain.contracts.common import JsonValue, require_revision
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
    content = payload.get("content") if isinstance(payload, Mapping) else None
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
    return meaning_from_json(
        result.output.value,
        source_event_id=request.source_event_ids[0],
        source_context_revision=current_source_context_revision,
        minimum_confidence=policy.minimum_confidence,
    )


class InputMeaningInterpreter:
    def __init__(self, port: LLMRolePort, policy: InputMeaningPolicy) -> None:
        self._port, self._policy = port, policy

    async def interpret(
        self,
        event: NormalizedInputEvent,
        context: ReferenceContext,
        *,
        request_id: str,
        trace_id: str,
        created_at: datetime,
        current_source_context_revision: int,
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
        return commit_result(
            request,
            result,
            current_source_context_revision=current_source_context_revision,
            policy=self._policy,
        )
