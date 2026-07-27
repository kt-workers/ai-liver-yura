from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from app.domain.actions import ActionPlanGroup
from app.domain.activities import ActivityStatus, ActivityType
from app.domain.events import AgentEvent, AgentEventType
from app.runtime.action_planner import ActionPlanner
from app.runtime.action_scheduler import ActionScheduler
from app.runtime.activity_manager import ActivityManager
from app.runtime.activity_result_builder import build_activity_result
from app.runtime.activity_turn_result_factory import (
    action_planning_failure_group,
    canceled_output_group,
)
from app.runtime.agent_life_service import AgentLifeService
from app.runtime.autonomous_activity_execution import prepare_autonomous_execution
from app.runtime.autonomous_output import completed_speech_text
from app.utils.trace import TraceLogger


class RuntimeEventExecutor:
    """AgentEventからActivityを生成し、通常のAction実行完了までを担当する。"""

    def __init__(
        self,
        *,
        activity_manager: ActivityManager,
        action_planner: ActionPlanner,
        action_scheduler: ActionScheduler,
        agent_life_service: AgentLifeService,
        event_enrichers_provider: Callable[
            [], tuple[Callable[[AgentEvent], AgentEvent], ...]
        ],
        trace_logger: TraceLogger,
    ) -> None:
        self._activity_manager = activity_manager
        self._action_planner = action_planner
        self._action_scheduler = action_scheduler
        self._agent_life_service = agent_life_service
        self._event_enrichers_provider = event_enrichers_provider
        self._trace_logger = trace_logger

    async def execute(self, event: AgentEvent) -> ActionPlanGroup:
        for enricher in self._event_enrichers_provider():
            event = enricher(event)

        # 既存の状態更新順序を維持する。重複呼び出しの整理は別工程とする。
        self._agent_life_service.handle_event(event)
        event = self._with_runtime_context(event)
        self._trace_logger.write(
            "runtime_coordinator:handle_event:start",
            event_type=event.event_type.value,
            event_id=event.event_id,
            priority=event.priority,
            discardable=event.discardable,
            replace_key=event.replace_key,
        )
        if self._is_agent_state_only_event(event):
            self._agent_life_service.handle_event(event)
            state = self._agent_life_service.agent_state
            self._trace_logger.write(
                "runtime_coordinator:handle_event:state_only",
                event_type=event.event_type.value,
                drive_curiosity=state.current_drive.curiosity,
                drive_engagement=state.current_drive.engagement,
                drive_boredom=state.current_drive.boredom,
                drive_energy=state.current_drive.energy,
            )
            return ActionPlanGroup()

        activity = self._activity_manager.handle_event(event)
        self._trace_logger.write(
            "runtime_coordinator:handle_event:activity_created",
            event_type=event.event_type.value,
            activity_type=activity.activity_type.value,
            activity_status=activity.status.value,
        )
        self._agent_life_service.handle_event(event)
        state = self._agent_life_service.agent_state
        self._trace_logger.write(
            "runtime_coordinator:handle_event:agent_state_updated",
            drive_curiosity=state.current_drive.curiosity,
            drive_engagement=state.current_drive.engagement,
            drive_boredom=state.current_drive.boredom,
            drive_energy=state.current_drive.energy,
        )
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
                event_id=event.event_id,
                failure_stage="action_planning",
                error_type=type(error).__name__,
            )
            self._activity_manager.complete_processed_activity(activity.activity_id)
            self._agent_life_service.sync_from_activity_manager()
            return action_plan_group

        self._trace_logger.write(
            "runtime_coordinator:handle_event:actions_planned",
            activity_type=activity.activity_type.value,
            action_types=[
                action_plan.action_type.value
                for action_plan in action_plan_group.action_plans
            ],
        )
        current_activity = self._activity_manager.get_activity(activity.activity_id)
        if (
            current_activity is not None
            and current_activity.status != ActivityStatus.ACTIVE
        ):
            self._trace_logger.info(
                "runtime_coordinator:handle_event:actions_canceled",
                event_id=event.event_id,
                activity_id=current_activity.activity_id,
                activity_type=current_activity.activity_type.value,
                activity_status=current_activity.status.value,
                action_ids=[
                    action.action_id for action in action_plan_group.action_plans
                ],
                action_types=[
                    action.action_type.value for action in action_plan_group.action_plans
                ],
                source_activity_ids=[
                    action.source_activity_id
                    for action in action_plan_group.action_plans
                ],
                reason="activity_suspended_before_action_execution",
            )
            canceled_group = canceled_output_group(
                action_plan_group,
                reason="activity_suspended_before_action_execution",
            )
            if canceled_group.activity_turn_result is not None:
                self._activity_manager.record_turn_result(
                    canceled_group.activity_turn_result
                )
            self._agent_life_service.sync_from_activity_manager()
            return canceled_group

        self._trace_logger.write(
            "runtime_coordinator:handle_event:actions_execute_start"
        )
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

        autonomous_output_saved = False
        if (
            activity.activity_type == ActivityType.AUTONOMOUS_TALK
            and output_result is not None
        ):
            speech_text = completed_speech_text(action_plan_group, output_result)
            if speech_text is not None:
                self._agent_life_service.record_autonomous_output(
                    activity_id=activity.activity_id,
                    text=speech_text,
                    context=activity.context,
                )
                autonomous_output_saved = True
                self._trace_logger.info(
                    "runtime_coordinator:autonomous_memory_saved",
                    activity_id=activity.activity_id,
                    output_unit_id=output_result.output_unit_id,
                    reason="speak_completed",
                )
            else:
                self._trace_logger.info(
                    "runtime_coordinator:autonomous_memory_not_saved",
                    activity_id=activity.activity_id,
                    output_unit_id=output_result.output_unit_id,
                    reason="speak_not_completed",
                )

        self._trace_logger.write(
            "runtime_coordinator:handle_event:actions_execute_finished"
        )
        completed_activity = self._activity_manager.complete_processed_activity(
            activity.activity_id,
            result=build_activity_result(action_plan_group, output_result),
        )
        if (
            activity.activity_type == ActivityType.AUTONOMOUS_TALK
            and autonomous_output_saved
        ):
            self._agent_life_service.complete_autonomous_topic(
                activity_id=activity.activity_id
            )
        self._trace_logger.write(
            "runtime_coordinator:handle_event:foreground_activity_completed",
            completed=completed_activity is not None,
            activity_id=(
                completed_activity.activity_id
                if completed_activity is not None
                else None
            ),
            activity_type=(
                completed_activity.activity_type.value
                if completed_activity is not None
                else None
            ),
            activity_status=(
                completed_activity.status.value
                if completed_activity is not None
                else None
            ),
        )
        self._agent_life_service.sync_from_activity_manager()
        state = self._agent_life_service.agent_state
        self._trace_logger.write(
            "runtime_coordinator:handle_event:agent_state_synced_after_activity_complete",
            active_activity_exists=state.active_activity is not None,
            pending_activity_count=len(state.pending_activities),
            suspended_activity_count=len(state.suspended_activities),
        )
        return action_plan_group

    def _with_runtime_context(self, event: AgentEvent) -> AgentEvent:
        if not isinstance(event.payload.get("relationship"), dict):
            relationship = self._agent_life_service.preview_relationship(event)
            if relationship is not None:
                event = replace(
                    event,
                    payload={
                        **event.payload,
                        "relationship": relationship.as_context(),
                    },
                )
        if not isinstance(event.payload.get("situation"), dict):
            event = replace(
                event,
                payload={
                    **event.payload,
                    "situation": (
                        self._agent_life_service.agent_state.current_situation.as_context()
                    ),
                },
            )
        if not isinstance(event.payload.get("memory"), dict):
            event = replace(
                event,
                payload={
                    **event.payload,
                    "memory": self._agent_life_service.agent_state.memory.as_context(),
                },
            )
        return event

    @staticmethod
    def _is_agent_state_only_event(event: AgentEvent) -> bool:
        return event.event_type in (
            AgentEventType.SPEECH_STARTED,
            AgentEventType.SPEECH_FINISHED,
        )
