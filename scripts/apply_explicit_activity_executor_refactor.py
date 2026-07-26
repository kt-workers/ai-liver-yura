from __future__ import annotations

from pathlib import Path


TARGET = Path("app/runtime/runtime_coordinator.py")


def replace_once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"置換対象の出現数が不正です: expected=1 actual={count}\n{old}"
        )
    return text.replace(old, new, 1)


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    if "self._explicit_activity_executor.execute" in text:
        return

    text = replace_once(
        text,
        "from app.runtime.event_type_router import EventTypeRouter\n",
        "from app.runtime.event_type_router import EventTypeRouter\n"
        "from app.runtime.explicit_activity_executor import ExplicitActivityExecutor\n",
    )
    text = replace_once(
        text,
        "        behavior_planning_context_builder: (\n"
        "            BehaviorPlanningContextBuilder | None\n"
        "        ) = None,\n",
        "        behavior_planning_context_builder: (\n"
        "            BehaviorPlanningContextBuilder | None\n"
        "        ) = None,\n"
        "        explicit_activity_executor: ExplicitActivityExecutor | None = None,\n",
    )
    text = replace_once(
        text,
        "        self._event_dispatch_processor = (\n",
        "        self._explicit_activity_executor = (\n"
        "            explicit_activity_executor\n"
        "            or ExplicitActivityExecutor(\n"
        "                activity_manager=self._activity_manager,\n"
        "                action_planner=self._action_planner,\n"
        "                action_scheduler=self._action_scheduler,\n"
        "                agent_life_service=self._agent_life_service,\n"
        "                trace_logger=self._trace_logger,\n"
        "            )\n"
        "        )\n"
        "        self._event_dispatch_processor = (\n",
    )

    old_method = '''    async def _execute_explicit_activity(self, activity: Activity) -> ActionPlanGroup:
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
            self._activity_manager.complete_processed_activity(activity.activity_id)
            self._agent_life_service.sync_from_activity_manager()
            raise
        action_plan_group = await self._action_scheduler.prepare(action_plan_group)
        output_result = await self._action_scheduler.execute(action_plan_group)
        if (
            output_result is not None
            and action_plan_group.activity_turn_result is not None
        ):
            self._activity_manager.record_output_result(
                action_plan_group.activity_turn_result, output_result
            )
        self._activity_manager.complete_processed_activity(activity.activity_id)
        self._agent_life_service.sync_from_activity_manager()
        return action_plan_group

'''
    new_method = '''    async def _execute_explicit_activity(self, activity: Activity) -> ActionPlanGroup:
        return await self._explicit_activity_executor.execute(activity)

'''
    text = replace_once(text, old_method, new_method)

    text = text.replace(
        "from app.runtime.activity_turn_result_factory import (\n"
        "    action_planning_failure_group,\n"
        "    canceled_output_group,\n"
        ")\n",
        "from app.runtime.activity_turn_result_factory import canceled_output_group\n",
    )
    text = text.replace(
        "from app.runtime.autonomous_activity_execution import prepare_autonomous_execution\n",
        "",
    )

    TARGET.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
