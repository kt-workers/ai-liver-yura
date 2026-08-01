from __future__ import annotations

from app.domain.activities import Activity, ActivityResult
from app.domain.events import AgentEvent, AgentEventType


def build_activity_result_desire_event(
    activity: Activity,
    result: ActivityResult,
) -> AgentEvent:
    """ActivityResultをDesire観測用の内部Eventへ変換する。"""

    output_status = result.data.get("output_status")
    normalized_status = output_status if isinstance(output_status, str) else None
    outcome = _resolve_outcome(
        succeeded=result.succeeded,
        output_status=normalized_status,
    )
    return AgentEvent(
        event_type=AgentEventType.ACTIVITY_RESULT_RECORDED,
        payload={
            "activity_id": activity.activity_id,
            "activity_type": activity.activity_type.value,
            "result_type": result.result_type,
            "outcome": outcome,
            "output_status": normalized_status,
            "trace_id": result.trace_id,
            "activity_turn_id": result.activity_turn_id,
        },
        occurred_at=result.created_at,
    )


def _resolve_outcome(
    *,
    succeeded: bool,
    output_status: str | None,
) -> str:
    if output_status == "partially_completed":
        return "partial"
    if output_status == "canceled":
        return "canceled"
    if not succeeded or output_status == "failed":
        return "failed"
    return "completed"
