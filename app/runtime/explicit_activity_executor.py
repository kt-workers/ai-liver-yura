from __future__ import annotations

from app.domain.actions import ActionPlanGroup
from app.domain.activities import Activity, ActivityResult
from app.runtime.action_planner import ActionPlanner
from app.runtime.action_scheduler import ActionScheduler
from app.runtime.activity_manager import ActivityManager
from app.runtime.activity_result_builder import build_activity_result
from app.runtime.activity_result_desire_event import (
    build_activity_result_desire_event,
)
from app.runtime.activity_turn_result_factory import action_planning_failure_group
from app.runtime.agent_life_service import AgentLifeService
from app.runtime.autonomous_activity_execution import prepare_autonomous_execution
from app.utils.trace import TraceLogger


class ExplicitActivityExecutor:
    """登録済みActivityを共通Action実行パイプラインへ流す。"""

    def __init__(
        self,
        *,
        activity_manager: ActivityManager,
        action_planner: ActionPlanner,
        action_scheduler: ActionScheduler,
        agent_life_service: AgentLifeService,
        trace_logger: TraceLogger,
    ) -> None:
        self._activity_manager = activity_manager
        self._action_planner = action_planner
        self._action_scheduler = action_scheduler
        self._agent_life_service = agent_life_service
        self._trace_logger = trace_logger

    async def execute(self, activity: Activity) -> ActionPlanGroup:
        prepare_autonomous_execution(activity)
        try:
            action_plan_group = await self._action_planner.plan(activity)
        except Exception as error:
            action_plan_group = action_planning_failure_group(activity, error)
            turn_result = action_plan_group.activity_turn_result
            if turn_result is not None:
                self._activity_manager.record_turn_result(turn_result)
            self._trace_logger.warning(
                "runtime_coordinator:action_planning:failed",
                activity_id=activity.activity_id,
                failure_stage="action_planning",
                error_type=type(error).__name__,
            )
            output_result = turn_result.output_result if turn_result is not None else None
            activity_result = build_activity_result(action_plan_group, output_result)
            self._complete(activity, activity_result)
            raise

        action_plan_group = await self._action_scheduler.prepare(action_plan_group)
        output_result = await self._action_scheduler.execute(action_plan_group)
        if (
            output_result is not None
            and action_plan_group.activity_turn_result is not None
        ):
            self._activity_manager.record_output_result(
                action_plan_group.activity_turn_result,
                output_result,
            )
        activity_result = build_activity_result(action_plan_group, output_result)
        self._complete(activity, activity_result)
        return action_plan_group

    def _complete(self, activity: Activity, result: ActivityResult) -> None:
        self._activity_manager.complete_processed_activity(
            activity.activity_id,
            result=result,
        )
        result_event = build_activity_result_desire_event(activity, result)
        self._agent_life_service.handle_event(result_event)
