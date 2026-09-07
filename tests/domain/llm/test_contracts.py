import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.domain.contracts import PreconditionRef, RevisionVector
from app.domain.llm import (
    LLMActivationPolicy,
    LLMExecutionPolicy,
    LLMFailureCode,
    LLMFailurePolicy,
    LLMInterruptibility,
    LLMModelClass,
    LLMPriority,
    LLMReasoningEffort,
    LLMRequestRetryPolicy,
    LLMRoleDescriptor,
    LLMRoleFailure,
    LLMRoleRequest,
    LLMRoleResult,
    LLMRoleStatus,
    LLMStalePolicy,
    LLMTokenUsage,
    StructuredPayload,
    validate_role_exchange,
)

NOW = datetime(2026, 8, 15, tzinfo=timezone.utc)
REVISIONS = RevisionVector(3, goal_revision=4, attention_revision=5)


def retry_policy() -> LLMRequestRetryPolicy:
    return LLMRequestRetryPolicy(0.25, 2.0, 2.0)


def policy() -> LLMExecutionPolicy:
    return LLMExecutionPolicy(
        "test.llm.execution",
        1,
        LLMModelClass.BALANCED,
        LLMReasoningEffort.MEDIUM,
        timeout_seconds=10,
        max_attempts=2,
        max_output_tokens=500,
        retry_policy=retry_policy(),
        temperature_normalized=0.4,
    )


def request() -> LLMRoleRequest:
    return LLMRoleRequest(
        "request-1",
        "input-meaning",
        StructuredPayload("input-meaning.v1", {"text": "こんにちは"}),
        ("event-1",),
        REVISIONS,
        (PreconditionRef("pre-1", "equals", "context", {"revision": 3}),),
        LLMPriority.FOREGROUND,
        LLMInterruptibility.INTERRUPTIBLE,
        LLMStalePolicy.REJECT,
        policy(),
        NOW,
        "trace-1",
        NOW + timedelta(seconds=10),
    )


def success() -> LLMRoleResult:
    return LLMRoleResult(
        "request-1",
        "input-meaning",
        LLMRoleStatus.SUCCEEDED,
        REVISIONS,
        NOW + timedelta(seconds=1),
        "trace-1",
        LLMModelClass.BALANCED,
        1,
        LLMTokenUsage(10, 5),
        StructuredPayload("structured-input-meaning.v1", {"meaning": "greeting"}),
        started_at=NOW,
    )


def descriptor() -> LLMRoleDescriptor:
    return LLMRoleDescriptor(
        "input-meaning",
        "外部入力の意味候補を構造化する",
        "input-meaning.v1",
        "structured-input-meaning.v1",
        "input.meaning.candidate",
        LLMActivationPolicy.REQUIRED,
        LLMFailurePolicy.FAIL_CLOSED,
        policy(),
    )


def failure(code: LLMFailureCode) -> LLMRoleFailure:
    return LLMRoleFailure(code, f"typed {code.value}")


def test_descriptor_is_variable_logical_role_contract() -> None:
    value = LLMRoleDescriptor(
        "speech-semantics",
        "Speech Intentで何を伝えるかを計画する",
        "speech-intent.v1",
        "speech-semantic-plan.v1",
        "speech.what-to-say.candidate",
        LLMActivationPolicy.CONDITIONAL,
        LLMFailurePolicy.DETERMINISTIC_FALLBACK,
        policy(),
    )
    assert value.to_dict()["role_id"] == "speech-semantics"
    json.dumps(value.to_dict(), allow_nan=False)


def test_exchange_validator_accepts_matching_role_schema_revision_and_trace() -> None:
    assert validate_role_exchange(descriptor(), request(), success()) is None


def test_exchange_validator_returns_typed_schema_failure_for_input_mismatch() -> None:
    value = request()
    mismatched = LLMRoleRequest(
        value.request_id,
        value.role_id,
        StructuredPayload("wrong-input.v1", {}),
        value.source_event_ids,
        value.revisions,
        value.preconditions,
        value.priority,
        value.interruptibility,
        value.stale_policy,
        value.execution_policy,
        value.created_at,
        value.trace_id,
        value.deadline_at,
    )
    failure_value = validate_role_exchange(descriptor(), mismatched, success())
    assert failure_value is not None
    assert failure_value.code is LLMFailureCode.SCHEMA_INVALID


def test_exchange_validator_returns_typed_schema_failure_for_output_mismatch() -> None:
    result = success()
    mismatched = LLMRoleResult(
        result.request_id,
        result.role_id,
        result.status,
        result.revisions,
        result.completed_at,
        result.trace_id,
        result.model_class,
        result.attempt_count,
        result.token_usage,
        StructuredPayload("wrong-output.v1", {}),
        started_at=result.started_at,
    )
    failure_value = validate_role_exchange(descriptor(), request(), mismatched)
    assert failure_value is not None
    assert failure_value.code is LLMFailureCode.SCHEMA_INVALID


@pytest.mark.parametrize("mismatch", ["request", "role", "trace", "revisions"])
def test_exchange_validator_rejects_transport_identity_mismatch(mismatch: str) -> None:
    result = success()
    invalid = LLMRoleResult(
        "wrong-request" if mismatch == "request" else result.request_id,
        "wrong-role" if mismatch == "role" else result.role_id,
        result.status,
        RevisionVector(999) if mismatch == "revisions" else result.revisions,
        result.completed_at,
        "wrong-trace" if mismatch == "trace" else result.trace_id,
        result.model_class,
        result.attempt_count,
        result.token_usage,
        result.output,
        started_at=result.started_at,
    )
    failure_value = validate_role_exchange(descriptor(), request(), invalid)
    assert failure_value is not None
    assert failure_value.code is LLMFailureCode.POLICY_VIOLATION


@pytest.mark.parametrize("field", ["started_at", "completed_at"])
def test_exchange_validator_rejects_result_timing_before_request_creation(field: str) -> None:
    result = success()
    before_request = request().created_at - timedelta(microseconds=1)
    started_at = before_request if field in ("started_at", "completed_at") else request().created_at
    completed_at = before_request if field == "completed_at" else result.completed_at
    invalid = LLMRoleResult(
        result.request_id,
        result.role_id,
        result.status,
        result.revisions,
        completed_at,
        result.trace_id,
        result.model_class,
        result.attempt_count,
        result.token_usage,
        result.output,
        started_at=started_at,
    )
    failure_value = validate_role_exchange(descriptor(), request(), invalid)
    assert failure_value is not None
    assert failure_value.code is LLMFailureCode.POLICY_VIOLATION


def test_exchange_validator_orders_request_result_timing_by_absolute_instant() -> None:
    zone = ZoneInfo("America/New_York")
    created = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0)
    later_same_wall_time = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=1)
    value = request()
    folded_request = LLMRoleRequest(
        value.request_id,
        value.role_id,
        value.input,
        value.source_event_ids,
        value.revisions,
        value.preconditions,
        value.priority,
        value.interruptibility,
        value.stale_policy,
        value.execution_policy,
        created,
        value.trace_id,
    )
    folded_result = LLMRoleResult(
        value.request_id,
        value.role_id,
        LLMRoleStatus.SUCCEEDED,
        value.revisions,
        later_same_wall_time,
        value.trace_id,
        LLMModelClass.BALANCED,
        1,
        LLMTokenUsage(1, 1),
        StructuredPayload("structured-input-meaning.v1", {"meaning": "greeting"}),
        started_at=later_same_wall_time,
    )
    assert validate_role_exchange(descriptor(), folded_request, folded_result) is None


def test_structured_payload_owns_strict_json_object() -> None:
    values = ["first"]
    payload = StructuredPayload(
        "schema.v1", {"values": values}  # type: ignore[dict-item]
    )
    values.append("mutated")
    assert payload.to_dict() == {"schema_id": "schema.v1", "value": {"values": ["first"]}}


@pytest.mark.parametrize("value", [[], "raw", 1, None])
def test_structured_payload_rejects_non_object_root(value: object) -> None:
    with pytest.raises(ValueError, match="JSON object"):
        StructuredPayload("schema.v1", value)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_structured_payload_rejects_non_finite_number(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        StructuredPayload("schema.v1", {"value": value})


def test_request_owns_tuple_fields_and_serializes_identity() -> None:
    events = ["event-1"]
    preconditions = [PreconditionRef("pre-1", "equals", "context", {"revision": 3})]
    value = LLMRoleRequest(
        "request-1",
        "input-meaning",
        StructuredPayload("input.v1", {}),
        events,  # type: ignore[arg-type]
        REVISIONS,
        preconditions,  # type: ignore[arg-type]
        LLMPriority.FOREGROUND,
        LLMInterruptibility.INTERRUPTIBLE,
        LLMStalePolicy.REJECT,
        policy(),
        NOW,
        "trace-1",
    )
    events.append("event-2")
    preconditions.clear()
    assert value.source_event_ids == ("event-1",)
    assert len(value.preconditions) == 1
    assert value.to_dict()["revisions"] == REVISIONS.to_dict()


def test_request_orders_dst_fold_deadline_by_absolute_instant() -> None:
    zone = ZoneInfo("America/New_York")
    created = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0)
    deadline = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=1)
    value = request()
    folded = LLMRoleRequest(
        value.request_id,
        value.role_id,
        value.input,
        value.source_event_ids,
        value.revisions,
        value.preconditions,
        value.priority,
        value.interruptibility,
        value.stale_policy,
        value.execution_policy,
        created,
        value.trace_id,
        deadline,
    )
    assert folded.deadline_at is deadline


@pytest.mark.parametrize("deadline", [NOW, NOW - timedelta(microseconds=1)])
def test_request_rejects_non_future_deadline(deadline: datetime) -> None:
    value = request()
    with pytest.raises(ValueError, match="later"):
        LLMRoleRequest(
            value.request_id,
            value.role_id,
            value.input,
            value.source_event_ids,
            value.revisions,
            value.preconditions,
            value.priority,
            value.interruptibility,
            value.stale_policy,
            value.execution_policy,
            NOW,
            value.trace_id,
            deadline,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("policy_id", ""),
        ("policy_revision", True),
        ("policy_revision", -1),
        ("timeout_seconds", True),
        ("timeout_seconds", float("inf")),
        ("max_attempts", True),
        ("max_attempts", 0),
        ("max_output_tokens", 1.5),
        ("temperature_normalized", float("nan")),
        ("temperature_normalized", 1.1),
    ],
)
def test_execution_policy_rejects_invalid_numeric_or_identity_value(
    field: str, value: object
) -> None:
    values: dict[str, object] = {
        "policy_id": "test.execution",
        "policy_revision": 1,
        "model_class": LLMModelClass.FAST,
        "reasoning_effort": LLMReasoningEffort.LOW,
        "timeout_seconds": 1,
        "max_attempts": 1,
        "max_output_tokens": 100,
        "retry_policy": retry_policy(),
        "temperature_normalized": None,
    }
    values[field] = value
    with pytest.raises(ValueError):
        LLMExecutionPolicy(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("values"),
    [
        (True, 2.0, 2.0),
        (0.0, 2.0, 2.0),
        (0.1, True, 2.0),
        (0.1, 0.9, 2.0),
        (0.5, 2.0, 0.4),
        (0.1, 2.0, float("inf")),
    ],
)
def test_retry_policy_rejects_invalid_values(values: tuple[object, object, object]) -> None:
    with pytest.raises(ValueError):
        LLMRequestRetryPolicy(*values)  # type: ignore[arg-type]


def test_retry_delay_is_deterministic_exponential_and_capped() -> None:
    retry = LLMRequestRetryPolicy(0.25, 2.0, 0.75)
    assert retry.delay_seconds(1) == 0.25
    assert retry.delay_seconds(2) == 0.5
    assert retry.delay_seconds(3) == 0.75
    assert retry.delay_seconds(10) == 0.75
    for invalid in (True, 0, -1):
        with pytest.raises(ValueError):
            retry.delay_seconds(invalid)


def test_execution_policy_serializes_generation_and_normalized_temperature() -> None:
    data = policy().to_dict()
    assert data["policy_id"] == "test.llm.execution"
    assert data["policy_revision"] == 1
    assert data["temperature_normalized"] == 0.4
    assert data["retry_policy"] == retry_policy().to_dict()


def test_succeeded_result_requires_started_output_and_no_failure() -> None:
    assert success().is_committable
    with pytest.raises(ValueError, match="requires start and output"):
        LLMRoleResult(
            "request-1",
            "input-meaning",
            LLMRoleStatus.SUCCEEDED,
            REVISIONS,
            NOW,
            "trace-1",
            LLMModelClass.FAST,
            1,
            LLMTokenUsage(0, 0),
        )


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (LLMRoleStatus.FAILED, LLMFailureCode.SCHEMA_INVALID),
        (LLMRoleStatus.FAILED, LLMFailureCode.PROVIDER_ERROR),
        (LLMRoleStatus.CANCELLED, LLMFailureCode.CANCELLED),
        (LLMRoleStatus.TIMED_OUT, LLMFailureCode.TIMEOUT),
        (LLMRoleStatus.STALE, LLMFailureCode.STALE),
        (LLMRoleStatus.SUPERSEDED, LLMFailureCode.SUPERSEDED),
        (LLMRoleStatus.REJECTED, LLMFailureCode.REJECTED),
    ],
)
def test_non_success_result_is_typed_and_non_committable(
    status: LLMRoleStatus, code: LLMFailureCode
) -> None:
    result = LLMRoleResult(
        "request-1",
        "input-meaning",
        status,
        REVISIONS,
        NOW,
        "trace-1",
        LLMModelClass.FAST,
        0,
        LLMTokenUsage(0, 0),
        failure=failure(code),
    )
    assert not result.is_committable
    json.dumps(result.to_dict(), allow_nan=False)


def test_result_rejects_status_failure_mismatch() -> None:
    with pytest.raises(ValueError, match="does not match"):
        LLMRoleResult(
            "request-1",
            "input-meaning",
            LLMRoleStatus.STALE,
            REVISIONS,
            NOW,
            "trace-1",
            LLMModelClass.FAST,
            1,
            LLMTokenUsage(1, 0),
            failure=failure(LLMFailureCode.TIMEOUT),
        )


@pytest.mark.parametrize("value", [True, -1, 1.5, "1"])
def test_result_attempt_count_is_strict_non_negative_int(value: object) -> None:
    valid = success()
    with pytest.raises(ValueError, match="attempt_count"):
        LLMRoleResult(
            valid.request_id,
            valid.role_id,
            valid.status,
            valid.revisions,
            valid.completed_at,
            valid.trace_id,
            valid.model_class,
            value,  # type: ignore[arg-type]
            valid.token_usage,
            valid.output,
            started_at=valid.started_at,
        )


def test_success_result_preserves_role_request_schema_revision_and_metrics() -> None:
    result = success()
    data = result.to_dict()
    assert data["role_id"] == "input-meaning"
    assert data["revisions"] == REVISIONS.to_dict()
    assert data["output"] == {
        "schema_id": "structured-input-meaning.v1",
        "value": {"meaning": "greeting"},
    }
    assert data["token_usage"] == {"input_tokens": 10, "output_tokens": 5}
