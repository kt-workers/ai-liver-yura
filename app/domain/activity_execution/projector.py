from __future__ import annotations

from app.domain.contracts import EventEnvelope

from .contracts import ActivityExecutionRecord


def to_execution_event(
    record: ActivityExecutionRecord, *, event_id: str, trace_id: str
) -> EventEnvelope:
    if not isinstance(record, ActivityExecutionRecord):
        raise ValueError("record must be ActivityExecutionRecord")
    invocation = record.invocation
    result = record.result
    return EventEnvelope(
        event_id,
        f"execution.{result.status.value}",
        "activity_execution",
        result.occurred_at,
        trace_id,
        result.revisions,
        {
            "command_id": result.command_id,
            "invocation_id": invocation.invocation_id,
            "decision_id": invocation.command.decision_id,
            "intent_id": invocation.command.intent_ref.intent_id,
            "operation_ref": invocation.operation_ref,
            "status": result.status.value,
            "effect_refs": result.effect_refs,
            "effect_uncertainty": record.effect_uncertainty.value,
            "details": result.details,
            "cancellation_reason": record.cancellation_reason,
            "cancellation_requested_at": None
            if record.cancellation_requested_at is None
            else record.cancellation_requested_at.isoformat(),
        },
        correlation_id=invocation.command.decision_id,
    )
