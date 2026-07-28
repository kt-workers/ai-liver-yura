from __future__ import annotations

from app.domain.actions import ActionPlanGroup
from app.domain.activities import Activity
from app.runtime.action_planner import ActionPlanner
from app.runtime.action_scheduler import ActionScheduler
from app.runtime.activity_manager import ActivityManager
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
            if action_plan_group.activity_turn_result is not None:
                self._activity_manager.record_turn_result(
                    action_plan_group.activity_turn_result
                )
            self._trace_logger.warning(
                "runtime_coordinator:action_planning:failed",
                activity_id=activity.activity_id,
                failure_stage="action_planning",
                error_type=type(error).__name__,
            )
            self._complete(activity)
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
        self._complete(activity)
        return action_plan_group

    def _complete(self, activity: Activity) -> None:
        self._activity_manager.complete_processed_activity(activity.activity_id)
        self._agent_life_service.sync_from_activity_manager()
