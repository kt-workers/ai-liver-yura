from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, replace
from typing import cast

from app.core.plugins import PluginManager
from app.domain.activities import Activity, ActivityStatus, ActivityType
from app.domain.behavior import ActivityPlan
from app.domain.events import AgentEvent
from app.runtime.activity_manager import ActivityManager
from app.runtime.behavior_planner import ActivityPlanValidator
from app.runtime.explicit_activity_executor import ExplicitActivityExecutor
from app.runtime.plugin_ongoing_activity_synchronizer import (
    PluginActivitySynchronizationError,
    PluginOngoingActivitySynchronizer,
)
from app.shared.contracts.plugins.runtime import (
    CommandHandler,
    PlannedActivityInterpreter,
    PluginCapability,
    UserIntentInterpreter,
)
from app.utils.trace import TraceLogger


class PluginActivityCoordinator:
    """Plugin Activityの選択・実行・Core Activity登録を調停する。"""

    def __init__(
        self,
        *,
        plugin_manager: PluginManager | None,
        activity_plan_validator: ActivityPlanValidator | None,
        activity_manager: ActivityManager,
        explicit_activity_executor: ExplicitActivityExecutor,
        ongoing_synchronizer: PluginOngoingActivitySynchronizer,
        conversation_fallback: Callable[[AgentEvent], AgentEvent],
        execution_fallback: Callable[
            [AgentEvent, list[dict[str, object]], str, float],
            AgentEvent,
        ],
        ongoing_transition_payload: Callable[..., dict[str, object]],
        trace_logger: TraceLogger,
    ) -> None:
        self._plugin_manager = plugin_manager
        self._validator = activity_plan_validator
        self._activity_manager = activity_manager
        self._explicit_activity_executor = explicit_activity_executor
        self._ongoing_synchronizer = ongoing_synchronizer
        self._conversation_fallback = conversation_fallback
        self._execution_fallback = execution_fallback
        self._ongoing_transition_payload = ongoing_transition_payload
        self._trace_logger = trace_logger

    async def route(
        self,
        event: AgentEvent,
        *,
        plugin_id: str | None = None,
        required_capability: str | None = None,
        activity_plan: ActivityPlan | None = None,
    ) -> AgentEvent | None:
        manager = self._plugin_manager
        if manager is None:
            return self._conversation_fallback(event)
        if activity_plan is not None and self._validator is not None:
            immediate_evaluation = self._validator.validate(activity_plan)
            activity_plan = immediate_evaluation.plan
            if not immediate_evaluation.accepted:
                self._trace_logger.info(
                    "activity_constraints:rejected_before_plugin_handler",
                    activity_type=activity_plan.activity_type,
                    reason=immediate_evaluation.result.data.get("reason"),
                )
                return self._fallback(
                    event,
                    contexts=[
                        {"activity_plan_result": asdict(immediate_evaluation.result)}
                    ],
                    reason=str(
                        immediate_evaluation.result.data.get("reason")
                        or "activity_plan_rejected_before_execution"
                    ),
                    confidence=activity_plan.confidence,
                )
        text = str(event.payload.get("text") or "")
        for plugin in manager.get_plugins_by_capability(
            PluginCapability.USER_INTENT_INTERPRETER.value
        ):
            if plugin_id is not None and plugin.plugin_id != plugin_id:
                continue
            planned_interpreter = getattr(plugin, "interpret_activity_plan", None)
            if activity_plan is not None and callable(planned_interpreter):
                intent_result = await cast(
                    PlannedActivityInterpreter,
                    plugin,
                ).interpret_activity_plan(activity_plan, text)
            else:
                intent_result = await cast(
                    UserIntentInterpreter,
                    plugin,
                ).interpret_user_text(text)
            if not intent_result.handled:
                continue
            if intent_result.conversation_context.get("execution_requested") is False:
                return replace(
                    event,
                    payload={
                        **event.payload,
                        "plugin_contexts": [dict(intent_result.conversation_context)],
                        **dict(intent_result.conversation_context),
                        "available_plugin_capabilities": sorted(
                            manager.list_capabilities()
                        ),
                        "execution_performed": False,
                    },
                )
            if required_capability is not None and not manager.is_capability_available(
                required_capability,
                plugin.plugin_id,
            ):
                self._trace_logger.warning(
                    "runtime_coordinator:activity_capability_rejected_before_execution",
                    plugin_id=plugin.plugin_id,
                    capability=required_capability,
                )
                return self._fallback(
                    event,
                    contexts=[dict(intent_result.conversation_context)],
                    reason="activity_capability_revoked_before_execution",
                    confidence=intent_result.confidence,
                )
            if not manager.is_capability_available(
                PluginCapability.COMMAND_HANDLER.value,
                plugin.plugin_id,
            ):
                self._trace_logger.warning(
                    "runtime_coordinator:capability_execution_rejected",
                    plugin_id=plugin.plugin_id,
                    capability=PluginCapability.COMMAND_HANDLER.value,
                    reason="unavailable_before_execution",
                )
                return self._fallback(
                    event,
                    contexts=[dict(intent_result.conversation_context)],
                    reason="selected_capability_unavailable",
                    confidence=intent_result.confidence,
                )
            self._trace_logger.info(
                "runtime_coordinator:capability_matched",
                plugin_id=plugin.plugin_id,
                capability=PluginCapability.COMMAND_HANDLER.value,
                confidence=intent_result.confidence,
            )
            operation = self._activity_operation(activity_plan, intent_result)
            constraints = activity_plan.constraints if activity_plan is not None else {}
            turn_started = False
            if operation != "start":
                try:
                    self._ongoing_synchronizer.begin_turn(
                        plugin=plugin,
                        operation=operation,
                        input_text=text,
                        source_event_id=event.event_id,
                        constraints=constraints,
                    )
                    turn_started = True
                except PluginActivitySynchronizationError as error:
                    return self._fallback(
                        event,
                        contexts=[dict(intent_result.conversation_context)],
                        reason=error.reason,
                        confidence=intent_result.confidence,
                    )
            execution = await cast(CommandHandler, plugin).execute_command(
                intent_result
            )
            for capability in execution.unavailable_capabilities:
                if manager.is_capability_available(capability, plugin.plugin_id):
                    manager.set_capability_availability(
                        plugin.plugin_id,
                        capability,
                        available=False,
                    )
                    self._trace_logger.warning(
                        "runtime_coordinator:capability_revoked_after_failure",
                        plugin_id=plugin.plugin_id,
                        capability=capability,
                        reason=execution.reason,
                    )
            if execution.handled and execution.activity_request is not None:
                request = execution.activity_request
                try:
                    execution_result, ongoing_snapshot = (
                        self._ongoing_synchronizer.synchronize(
                            plugin=plugin,
                            activity_state=request.state,
                            request_context=dict(request.context),
                            activity_kind=request.activity_kind,
                            activity_type=(
                                activity_plan.activity_type
                                if activity_plan is not None
                                else request.activity_kind
                            ),
                            response_text=request.response_text,
                            capability=required_capability,
                            operation=operation,
                            constraints=constraints,
                            goal=(
                                activity_plan.goal
                                if activity_plan is not None
                                else (
                                    f"Plugin {request.plugin_id} "
                                    "の継続Activityを実行する"
                                )
                            ),
                            input_text=text,
                            source_event_id=event.event_id,
                            turn_started=turn_started,
                        )
                    )
                except Exception as error:
                    self._trace_logger.error(
                        "runtime_coordinator:plugin_ongoing_activity_sync_failed",
                        plugin_id=plugin.plugin_id,
                        operation=operation,
                        error_type=type(error).__name__,
                    )
                    return self._fallback(
                        event,
                        contexts=[dict(request.context)],
                        reason="ongoing_activity_sync_failed",
                        confidence=intent_result.confidence,
                    )
                activity = Activity(
                    activity_type=ActivityType.PLUGIN_ACTIVITY,
                    goal=f"Plugin {request.plugin_id} のActivityを実行する",
                    priority=request.priority,
                    context={
                        **dict(request.context),
                        "plugin_id": request.plugin_id,
                        "prepared_response_text": request.response_text,
                        "plugin_memory_policy": request.memory_policy,
                        "ongoing_activity": ongoing_snapshot,
                        "ongoing_activity_id": ongoing_snapshot.ongoing_activity_id,
                        "activity_execution_result": execution_result,
                        "ongoing_transition": self._ongoing_transition_payload(
                            activity_plan,
                            current_status=ongoing_snapshot.status.value,
                            stopped=(
                                operation == "stop"
                                and ongoing_snapshot.status
                                in {
                                    ActivityStatus.COMPLETED,
                                    ActivityStatus.CANCELED,
                                }
                            ),
                            transition_result="succeeded",
                        ),
                    },
                    interruptible=False,
                )
                registered = self._activity_manager.register_plugin_activity(activity)
                await self._explicit_activity_executor.execute(registered)
                self._trace_logger.info(
                    "runtime_coordinator:plugin_activity_executed",
                    plugin_id=request.plugin_id,
                    activity_id=registered.activity_id,
                    activity_kind=request.activity_kind,
                )
                return None
            if bool(execution.conversation_context.get("execution_requested")):
                if turn_started:
                    self._ongoing_synchronizer.record_failed_turn(
                        activity_type=(
                            activity_plan.activity_type
                            if activity_plan is not None
                            else "plugin_activity"
                        ),
                        operation=operation,
                        capability=required_capability,
                        plugin_id=plugin.plugin_id,
                        reason=execution.reason or "execution_not_completed",
                        constraints=constraints,
                        conversation_context=dict(execution.conversation_context),
                        activity_state=execution.activity_state,
                    )
                return self._fallback(
                    event,
                    contexts=[dict(execution.conversation_context)],
                    reason=execution.reason or "execution_not_completed",
                    confidence=intent_result.confidence,
                )
            return replace(
                event,
                payload={
                    **event.payload,
                    "plugin_contexts": [dict(execution.conversation_context)],
                    **dict(execution.conversation_context),
                    "plugin_intent_reason": intent_result.reason,
                    "available_plugin_capabilities": sorted(
                        manager.list_capabilities()
                    ),
                    "execution_performed": False,
                },
            )
        return self._conversation_fallback(event)

    def _fallback(
        self,
        event: AgentEvent,
        *,
        contexts: list[dict[str, object]],
        reason: str,
        confidence: float,
    ) -> AgentEvent:
        return self._execution_fallback(event, contexts, reason, confidence)

    @staticmethod
    def _activity_operation(
        activity_plan: ActivityPlan | None,
        intent_result: object,
    ) -> str:
        if activity_plan is not None and activity_plan.operation is not None:
            return activity_plan.operation.value
        command = getattr(intent_result, "command", None)
        operation = getattr(command, "operation", None)
        return str(operation) if operation is not None else "continue"
