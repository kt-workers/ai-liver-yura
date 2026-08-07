from __future__ import annotations

from dataclasses import asdict, replace

from app.core.plugins import PluginManager
from app.domain.activities import ActivityType
from app.domain.behavior import (
    ActivityOperation,
    ActivityPlan,
    ActivityPlanEvaluation,
    BehaviorDecision,
)
from app.domain.character_response import (
    ActivityExecutionResult,
    ActivityExecutionStatus,
)
from app.domain.events import AgentEvent, AgentEventType
from app.runtime.activity_switch_coordinator import ActivitySwitchCoordinator
from app.runtime.behavior_planner import ActivityPlanValidator, BehaviorPlanner
from app.runtime.behavior_planning_context_builder import (
    BehaviorPlanningContextBuilder,
)
from app.runtime.behavior_routing_support import (
    BehaviorFallbackRouter,
    ongoing_transition_payload,
    plan_payload,
)
from app.runtime.confirmation_coordinator import ConfirmationCoordinator
from app.runtime.plugin_activity_coordinator import PluginActivityCoordinator
from app.utils.trace import TraceLogger


class BehaviorRoutingCoordinator:
    """Behavior計画・検証・実行先選択と診断状態を所有する。"""

    def __init__(
        self,
        *,
        planner: BehaviorPlanner | None,
        validator: ActivityPlanValidator | None,
        plugin_manager: PluginManager | None,
        context_builder: BehaviorPlanningContextBuilder | None,
        confirmation_coordinator: ConfirmationCoordinator | None,
        plugin_activity_coordinator: PluginActivityCoordinator,
        activity_switch_coordinator: ActivitySwitchCoordinator,
        fallback_router: BehaviorFallbackRouter,
        trace_logger: TraceLogger,
    ) -> None:
        self._planner = planner
        self._validator = validator
        self._plugin_manager = plugin_manager
        self._context_builder = context_builder
        self._confirmation = confirmation_coordinator
        self._plugin_activity = plugin_activity_coordinator
        self._activity_switch = activity_switch_coordinator
        self._fallback = fallback_router
        self._trace_logger = trace_logger
        self._last_evaluation: ActivityPlanEvaluation | None = None
        self._last_fallback_plan: ActivityPlan | None = None

    @property
    def last_evaluation(self) -> ActivityPlanEvaluation | None:
        return self._last_evaluation

    @property
    def last_fallback_plan(self) -> ActivityPlan | None:
        return self._last_fallback_plan

    async def route(self, event: AgentEvent) -> AgentEvent | None:
        planner = self._planner
        validator = self._validator
        if (
            planner is None
            or validator is None
            or self._plugin_manager is None
            or self._context_builder is None
        ):
            return self._fallback.with_plugin_availability(event)
        preparation = self._context_builder.build(event)
        event = preparation.event
        planning_context = preparation.context
        ongoing = preparation.ongoing_activity
        situation_payload: dict[str, object]
        confirmation_payload: dict[str, object] = {}
        plan: ActivityPlan | None = None
        confirmation = self._confirmation
        if confirmation is not None:
            confirmation_result = confirmation.route_pending(
                event,
                planning_context,
            )
            if confirmation_result is not None:
                event = confirmation_result.event
                planning_context = confirmation_result.planning_context
                plan = confirmation_result.plan
                situation_payload = confirmation_result.situation_payload
                confirmation_payload = confirmation_result.confirmation_payload
                if confirmation_result.terminal_event is not None:
                    return confirmation_result.terminal_event
        if plan is None and event.event_type == AgentEventType.APP_STARTED:
            situation_payload = {
                "event_type": AgentEventType.APP_STARTED.value,
                "lifecycle_phase": "awakening",
                "speech_required": False,
            }
            awakening_value = event.payload.get("awakening_context")
            if isinstance(awakening_value, dict) and awakening_value:
                situation_payload["awakening_context"] = dict(awakening_value)
            plan = ActivityPlan(
                decision=BehaviorDecision.START_ACTIVITY,
                activity_type=ActivityType.AWAKENING.value,
                goal="起動後の状態を整え、発話せずに周囲を認識する",
                required_capability=None,
                provider_plugin_id="runtime",
                operation=ActivityOperation.START,
                reason="app_started_runtime_activity",
                planning_reason="app_started",
            )
        elif plan is None:
            situation = await planner.evaluate_situation(planning_context)
            plan = await planner.plan(planning_context, situation)
            situation_payload = asdict(situation)
        if plan.decision == BehaviorDecision.ASK_CONFIRMATION:
            if confirmation is None:
                return self._fallback.with_plugin_availability(event)
            self._last_evaluation = validator.validate(plan)
            self._last_fallback_plan = None
            return confirmation.request_confirmation(
                event,
                plan,
                current_ongoing_activity_id=(
                    ongoing.ongoing_activity_id if ongoing is not None else None
                ),
                situation_payload=situation_payload,
            )
        evaluation = validator.validate(plan)
        plan = evaluation.plan
        event = replace(
            event,
            trace_context=event.trace_context.derive(
                behavior_plan_id=plan.behavior_plan_id
            ),
        )
        self._last_evaluation = evaluation
        self._last_fallback_plan = None
        self._trace_logger.info(
            "behavior_planner:activity_plan_evaluated",
            **event.trace_context.as_log_fields(),
            decision=plan.decision.value,
            activity_type=plan.activity_type,
            operation=plan.operation.value if plan.operation else None,
            speech_act=plan.speech_act.value,
            required_capability=plan.required_capability,
            provider_plugin_id=plan.provider_plugin_id,
            accepted=evaluation.accepted,
            reason=plan.reason,
        )
        behavior_payload: dict[str, object] = {
            "situation_analysis": situation_payload,
            "behavior_plan": plan_payload(plan),
            "behavior_plan_result": asdict(evaluation.result),
            "ongoing_transition": ongoing_transition_payload(
                plan,
                current_status=ongoing.status.value if ongoing is not None else None,
            ),
            **confirmation_payload,
            "trace_context": event.trace_context,
        }
        if not evaluation.accepted:
            behavior_payload["activity_execution_result"] = ActivityExecutionResult(
                activity_type=plan.activity_type,
                operation=plan.operation.value if plan.operation else None,
                status=ActivityExecutionStatus.REJECTED,
                capability=plan.required_capability,
                provider=plan.provider_plugin_id,
                payload={"summary": evaluation.result.summary},
                failure_reason=str(
                    evaluation.result.data.get("reason") or "activity_rejected"
                ),
                constraints=plan.constraints,
                source_event_id=event.event_id,
                trace_id=event.trace_context.trace_id,
                parent_trace_id=event.trace_context.parent_trace_id,
                behavior_plan_id=plan.behavior_plan_id,
            )
            fallback_plan = planner.fallback_after_rejection(evaluation)
            self._last_fallback_plan = fallback_plan
            behavior_payload["behavior_fallback_plan"] = plan_payload(fallback_plan)
            fallback_event = self._fallback.with_execution_fallback(
                event,
                contexts=[{"activity_plan_result": asdict(evaluation.result)}],
                reason="activity_capability_rejected",
                confidence=plan.confidence,
            )
            return replace(
                fallback_event,
                payload={**fallback_event.payload, **behavior_payload},
            )
        if plan.decision == BehaviorDecision.SWITCH_ACTIVITY:
            routed = await self._activity_switch.route(
                event,
                plan,
                planning_context,
            )
            if routed is None:
                return None
        elif plan.required_capability is not None:
            routed = await self._plugin_activity.route(
                event,
                plugin_id=plan.provider_plugin_id,
                required_capability=plan.required_capability,
                activity_plan=plan,
            )
            if routed is None:
                return None
        else:
            routed = self._fallback.with_plugin_availability(event)
            execution_rejected = bool(routed.payload.get("execution_request_unmatched"))
            behavior_payload["activity_execution_result"] = ActivityExecutionResult(
                activity_type=plan.activity_type,
                operation=plan.operation.value if plan.operation else None,
                status=(
                    ActivityExecutionStatus.REJECTED
                    if execution_rejected
                    else ActivityExecutionStatus.WAITING_INPUT
                ),
                payload={
                    "summary": (
                        "要求された外部処理は実行されなかった"
                        if execution_rejected
                        else "Conversation Activityの応答Turnを生成する"
                    )
                },
                failure_reason=(
                    str(routed.payload.get("execution_match_reason"))
                    if execution_rejected
                    else None
                ),
                constraints=plan.constraints,
                source_event_id=event.event_id,
                trace_id=event.trace_context.trace_id,
                parent_trace_id=event.trace_context.parent_trace_id,
                behavior_plan_id=plan.behavior_plan_id,
            )
        return replace(routed, payload={**routed.payload, **behavior_payload})
