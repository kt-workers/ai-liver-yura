from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, cast

from app.domain.contracts.common import JsonValue, freeze_json
from app.domain.input_gateway import InputModality, NormalizedInputEvent
from app.domain.llm import (
    LLMActivationPolicy,
    LLMExecutionPolicy,
    LLMFailureCode,
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
    InputMeaningAcceptancePolicy,
    InputMeaningBoundaryFailure,
    InputMeaningFreshnessStamp,
    InputMeaningInterpretationResult,
    ReferenceContext,
    StructuredInputMeaning,
    meaning_from_json,
)

INPUT_SCHEMA = "yura.input-meaning.request.v1"
OUTPUT_SCHEMA = "yura.input-meaning.result.v1"
ROLE_ID = "input_meaning"


@dataclass(frozen=True, slots=True)
class InputMeaningPolicy:
    execution: LLMExecutionPolicy
    acceptance: InputMeaningAcceptancePolicy

    def __post_init__(self) -> None:
        if not isinstance(self.acceptance, InputMeaningAcceptancePolicy):
            raise ValueError("acceptance は InputMeaningAcceptancePolicy でなければなりません")


class InputMeaningLiveContextPort(Protocol):
    """Input Meaning commit直前の世代付き採用状態を読み取る境界。"""

    async def current_freshness_stamp(self) -> InputMeaningFreshnessStamp: ...


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
            "acceptance_policy": policy.acceptance.to_dict(),
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


class _CommitRejected(ValueError):
    """純粋な採用検証の拒否理由を、文字列解析せず公開境界へ渡す。"""

    def __init__(self, code: LLMFailureCode, message: str) -> None:
        super().__init__(message)
        self.code = code


def commit_result(
    request: LLMRoleRequest,
    result: LLMRoleResult,
    *,
    reference_context: ReferenceContext,
    freshness_stamp: InputMeaningFreshnessStamp,
    policy: InputMeaningPolicy,
) -> StructuredInputMeaning:
    if not isinstance(freshness_stamp, InputMeaningFreshnessStamp):
        raise ValueError("freshness_stamp は InputMeaningFreshnessStamp でなければなりません")
    failure = validate_role_exchange(descriptor(policy), request, result)
    if failure is not None:
        raise _CommitRejected(failure.code, failure.code.value)
    if result.status is not LLMRoleStatus.SUCCEEDED or result.output is None:
        raise _CommitRejected(LLMFailureCode.POLICY_VIOLATION, "非成功の入力意味は採用できません")
    if request.revisions.source_context_revision != freshness_stamp.source_context_revision:
        raise _CommitRejected(LLMFailureCode.STALE, "入力意味の結果が古くなっています")
    if (
        freshness_stamp.acceptance_policy_id != policy.acceptance.policy_id
        or freshness_stamp.acceptance_policy_revision != policy.acceptance.policy_revision
    ):
        raise _CommitRejected(LLMFailureCode.STALE, "入力意味の採用方針が古くなっています")
    request_value = request.input.value
    if not isinstance(request_value, Mapping):
        raise _CommitRejected(LLMFailureCode.POLICY_VIOLATION, "入力意味の要求構造が不正です")
    encoded_context = request_value.get("reference_context")
    if encoded_context != freeze_json(reference_context.to_dict()):
        raise _CommitRejected(
            LLMFailureCode.POLICY_VIOLATION, "参照文脈が要求時の固定内容と一致しません"
        )
    encoded_acceptance = request_value.get("acceptance_policy")
    if encoded_acceptance != freeze_json(policy.acceptance.to_dict()):
        raise _CommitRejected(
            LLMFailureCode.POLICY_VIOLATION, "採用方針が要求時の固定内容と一致しません"
        )
    try:
        meaning = meaning_from_json(
            result.output.value,
            source_event_id=request.source_event_ids[0],
            source_context_revision=request.revisions.source_context_revision,
            acceptance_policy=policy.acceptance,
        )
    except (ValueError, TypeError, KeyError) as error:
        raise _CommitRejected(LLMFailureCode.SCHEMA_INVALID, str(error)) from error
    allowed_refs = {
        value
        for item in reference_context.entries
        for value in (item.reference_id, item.subject_ref)
    }
    if any(
        item.resolved_ref is not None and item.resolved_ref not in allowed_refs
        for item in meaning.references
    ):
        raise _CommitRejected(
            LLMFailureCode.POLICY_VIOLATION,
            "解決した参照が参照文脈の範囲外です",
        )
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
    ) -> InputMeaningInterpretationResult:
        request = build_request(
            event,
            context,
            request_id=request_id,
            trace_id=trace_id,
            created_at=created_at,
            policy=self._policy,
        )
        result = await self._port.invoke(request)

        def reject(
            code: LLMFailureCode, message: str, status: LLMRoleStatus | None
        ) -> InputMeaningInterpretationResult:
            return InputMeaningInterpretationResult(
                request.request_id,
                request.trace_id,
                request.source_event_ids[0],
                request.revisions.source_context_revision,
                status,
                boundary_failure=InputMeaningBoundaryFailure(code, message),
            )

        exchange_failure = validate_role_exchange(descriptor(self._policy), request, result)
        if exchange_failure is not None:
            return reject(exchange_failure.code, "応答の識別または交換契約が不正です", None)
        if result.status is not LLMRoleStatus.SUCCEEDED:
            return InputMeaningInterpretationResult(
                request.request_id,
                request.trace_id,
                request.source_event_ids[0],
                request.revisions.source_context_revision,
                result.status,
                role_failure=result.failure,
            )
        try:
            freshness_stamp = await self._live_context.current_freshness_stamp()
        except Exception:
            # 外部取消はBaseExceptionであり、この運用上の取得失敗には含めない。
            return reject(LLMFailureCode.REJECTED, "現在世代を取得できません", result.status)
        if not isinstance(freshness_stamp, InputMeaningFreshnessStamp):
            return reject(LLMFailureCode.REJECTED, "現在世代を確定できません", result.status)
        try:
            meaning = commit_result(
                request,
                result,
                reference_context=context,
                freshness_stamp=freshness_stamp,
                policy=self._policy,
            )
        except _CommitRejected as error:
            return reject(error.code, "入力意味の採用条件を満たしていません", result.status)
        return InputMeaningInterpretationResult(
            request.request_id,
            request.trace_id,
            request.source_event_ids[0],
            request.revisions.source_context_revision,
            result.status,
            meaning=meaning,
        )
