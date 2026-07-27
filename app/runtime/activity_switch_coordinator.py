from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import asdict

from app.domain.activities import OngoingActivity
from app.domain.behavior import (
    ActivityOperation,
    ActivityPlan,
    BehaviorDecision,
    BehaviorPlanningContext,
)
from app.domain.events import AgentEvent
from app.runtime.behavior_planner import ActivityPlanValidator
from app.utils.trace import TraceLogger


class ActivitySwitchCoordinator:
    """現在Activityの停止完了を保証してから新Activityを開始する。"""

    def __init__(
        self,
        *,
        validator: ActivityPlanValidator | None,
        plugin_router: Callable[..., Awaitable[AgentEvent | None]],
        current_ongoing_activity: Callable[[], OngoingActivity | None],
        execution_fallback: Callable[
            [AgentEvent, list[dict[str, object]], str, float],
            AgentEvent,
        ],
        trace_logger: TraceLogger,
    ) -> None:
        self._validator = validator
        self._plugin_router = plugin_router
        self._current_ongoing_activity = current_ongoing_activity
        self._execution_fallback = execution_fallback
        self._trace_logger = trace_logger

    async def route(
        self,
        event: AgentEvent,
        plan: ActivityPlan,
        planning_context: BehaviorPlanningContext,
        *,
        plugin_router: Callable[..., Awaitable[AgentEvent | None]] | None = None,
    ) -> AgentEvent | None:
        route_plugin = plugin_router or self._plugin_router
        validator = self._validator
        current = planning_context.active_activity_definition
        if validator is None or current is None:
            return self._fallback(
                event,
                contexts=[],
                reason="switch_current_activity_definition_missing",
                confidence=plan.confidence,
            )
        stop_plan = ActivityPlan(
            decision=BehaviorDecision.CONTINUE_ACTIVITY,
            activity_type=current.activity_type,
            goal=f"{current.display_name}を停止してActivityを切り替える",
            required_capability=current.required_capability,
            provider_plugin_id=current.provider_plugin_id,
            operation=ActivityOperation.STOP,
            planner_constraints=("停止成功後だけ新しいActivityを開始する",),
            speech_act=plan.speech_act,
            confidence=plan.confidence,
            reason="switch_stop_current",
            ongoing_input_decision=plan.ongoing_input_decision,
            current_activity_type=current.activity_type,
        )
        stop_evaluation = validator.validate(stop_plan)
        if not stop_evaluation.accepted:
            self._trace_logger.warning(
                "runtime_coordinator:activity_switch_stop_rejected",
                current_activity_type=current.activity_type,
                requested_activity_type=plan.activity_type,
            )
            return self._fallback(
                event,
                contexts=[{"stop_result": asdict(stop_evaluation.result)}],
                reason="switch_stop_rejected",
                confidence=plan.confidence,
            )
        stop_routed = await route_plugin(
            event,
            plugin_id=current.provider_plugin_id,
            required_capability=current.required_capability,
            activity_plan=stop_plan,
        )
        if stop_routed is not None or self._current_ongoing_activity() is not None:
            self._trace_logger.warning(
                "runtime_coordinator:activity_switch_stop_failed",
                current_activity_type=current.activity_type,
                requested_activity_type=plan.activity_type,
            )
            return self._fallback(
                stop_routed or event,
                contexts=[],
                reason="switch_stop_failed",
                confidence=plan.confidence,
            )
        routed = await route_plugin(
            event,
            plugin_id=plan.provider_plugin_id,
            required_capability=plan.required_capability,
            activity_plan=plan,
        )
        self._trace_logger.info(
            "runtime_coordinator:activity_switch_finished",
            previous_activity_type=current.activity_type,
            requested_activity_type=plan.activity_type,
            started=routed is None,
        )
        return routed

    def _fallback(
        self,
        event: AgentEvent,
        *,
        contexts: list[dict[str, object]],
        reason: str,
        confidence: float,
    ) -> AgentEvent:
        return self._execution_fallback(event, contexts, reason, confidence)
