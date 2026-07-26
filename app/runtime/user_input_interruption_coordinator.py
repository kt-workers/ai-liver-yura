from __future__ import annotations

from app.domain.activities import Activity, ActivityType
from app.domain.events import AgentEvent, AgentEventType
from app.runtime.action_scheduler import ActionScheduler
from app.runtime.activity_executor_thread import ActivityExecutorThread
from app.runtime.activity_manager import ActivityManager
from app.runtime.activity_planner_thread import ActivityPlannerThread
from app.runtime.agent_life_service import AgentLifeService
from app.utils.trace import TraceLogger


class UserInputInterruptionCoordinator:
    """ユーザー入力に伴う自律活動の中断と会話Activity準備を調停する。"""

    def __init__(
        self,
        *,
        activity_manager: ActivityManager,
        action_scheduler: ActionScheduler,
        activity_planner_thread: ActivityPlannerThread,
        activity_executor_thread: ActivityExecutorThread,
        agent_life_service: AgentLifeService,
        trace_logger: TraceLogger,
    ) -> None:
        self._activity_manager = activity_manager
        self._action_scheduler = action_scheduler
        self._activity_planner_thread = activity_planner_thread
        self._activity_executor_thread = activity_executor_thread
        self._agent_life_service = agent_life_service
        self._trace_logger = trace_logger

    def before_routing(
        self,
        event: AgentEvent,
        *,
        foreground_at_receipt: Activity | None,
    ) -> None:
        """ユーザー入力のルーティング前に、再生待ちの自律発話を停止する。"""

        if event.event_type != AgentEventType.USER_TEXT:
            return
        if (
            foreground_at_receipt is not None
            and foreground_at_receipt.activity_type == ActivityType.AUTONOMOUS_TALK
        ):
            self._action_scheduler.cancel_pending_segments(
                foreground_at_receipt.activity_id
            )

    def after_prioritization(
        self,
        event: AgentEvent,
        *,
        foreground_at_receipt: Activity | None,
    ) -> Activity | None:
        """優先度付与後に会話Activityを準備し、自律処理を中断する。"""

        prepared_activity = self._activity_manager.prepare_user_input(event)
        if event.event_type == AgentEventType.USER_TEXT:
            self._activity_planner_thread.cancel_inflight_autonomous(
                source_event_id=event.event_id,
                trace_context=event.trace_context,
            )
            if (
                foreground_at_receipt is not None
                and foreground_at_receipt.activity_type
                == ActivityType.AUTONOMOUS_TALK
            ):
                self._agent_life_service.interrupt_autonomous_topic(
                    activity_id=foreground_at_receipt.activity_id,
                    fallback_text=foreground_at_receipt.goal,
                )
            discarded_deferred = self._activity_manager.discard_deferred_autonomous(
                reason="user_conversation_started"
            )
            canceled = self._activity_executor_thread.cancel_pending_autonomous(
                source_event_id=event.event_id,
                reason="user_text_received",
            )
            if canceled:
                self._trace_logger.info(
                    "runtime_coordinator:user_input:pending_autonomous_canceled",
                    event_id=event.event_id,
                    planned_activity_ids=[
                        item.planned_activity_id for item in canceled
                    ],
                    activity_ids=[item.activity.activity_id for item in canceled],
                )
            if discarded_deferred:
                self._trace_logger.info(
                    "runtime_coordinator:user_input:deferred_autonomous_discarded",
                    event_id=event.event_id,
                    activity_ids=[
                        activity.activity_id for activity in discarded_deferred
                    ],
                    reason="restart_with_fresh_context_after_conversation",
                )

        if prepared_activity is not None:
            self._agent_life_service.sync_from_activity_manager()
            self._trace_logger.info(
                "runtime_coordinator:user_input:conversation_prepared",
                event_id=event.event_id,
                activity_id=prepared_activity.activity_id,
                activity_type=prepared_activity.activity_type.value,
            )
        return prepared_activity
