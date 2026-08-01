from app.domain.activities import Activity, ActivityResult, ActivityType
from app.domain.events import AgentEventType
from app.runtime.activity_result_desire_event import (
    build_activity_result_desire_event,
)


def _activity() -> Activity:
    return Activity(
        activity_type=ActivityType.TOPIC_EXPLORATION,
        goal="話題を探索する",
    )


def test_factory_builds_completed_activity_result_event() -> None:
    result = ActivityResult(
        result_type="speech_output",
        summary="探索結果",
        data={"output_status": "completed"},
        succeeded=True,
        trace_id="trace-1",
        activity_turn_id="turn-1",
    )

    event = build_activity_result_desire_event(_activity(), result)

    assert event.event_type == AgentEventType.ACTIVITY_RESULT_RECORDED
    assert event.payload["activity_type"] == "topic_exploration"
    assert event.payload["outcome"] == "completed"
    assert event.payload["result_type"] == "speech_output"
    assert event.payload["trace_id"] == "trace-1"
    assert event.payload["activity_turn_id"] == "turn-1"


def test_factory_distinguishes_partial_canceled_and_failed() -> None:
    activity = _activity()
    partial = ActivityResult(
        result_type="action_output",
        summary="一部成功",
        data={"output_status": "partially_completed"},
        succeeded=False,
    )
    canceled = ActivityResult(
        result_type="action_output",
        summary="中断",
        data={"output_status": "canceled"},
        succeeded=False,
    )
    failed = ActivityResult(
        result_type="action_output",
        summary="失敗",
        data={"output_status": "failed"},
        succeeded=False,
    )

    assert (
        build_activity_result_desire_event(activity, partial).payload["outcome"]
        == "partial"
    )
    assert (
        build_activity_result_desire_event(activity, canceled).payload["outcome"]
        == "canceled"
    )
    assert (
        build_activity_result_desire_event(activity, failed).payload["outcome"]
        == "failed"
    )
