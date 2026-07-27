from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import asdict, replace
from queue import Queue
from time import monotonic
from typing import Any, cast

from app.core.plugins import PluginManager
from app.core.plugins.user_request import UserRequestKind, interpret_user_request
from app.domain.actions import ActionPlanGroup
from app.domain.activities import (
    Activity,
    ActivityStatus,
    ActivityType,
)
from app.domain.activity_turn_result import ActivityTurnResult
from app.domain.behavior import (
    ActivityOperation,
    ActivityPlan,
    ActivityPlanEvaluation,
    BehaviorDecision,
    BehaviorPlanningContext,
)
from app.domain.character_response import (
    ActivityExecutionResult,
    ActivityExecutionStatus,
)
from app.domain.events import AgentEvent, AgentEventType, InputAuthority
from app.domain.pending_confirmation import PendingConfirmation
from app.domain.short_term_memory import ShortTermMemory
from app.domain.topic import TopicHistory
from app.runtime.action_planner import ActionPlanner
from app.runtime.action_scheduler import ActionScheduler
from app.runtime.activity_executor_thread import ActivityExecutorThread
from app.runtime.activity_manager import ActivityManager
from app.runtime.activity_planner_thread import (
    ActivityPlannerThread,
    ActivityPlanningRequest,
)
from app.runtime.activity_registry import ActivityRegistry
from app.runtime.activity_result_builder import build_activity_result
from app.runtime.activity_switch_coordinator import ActivitySwitchCoordinator
from app.runtime.activity_turn_result_factory import (
    action_planning_failure_group,
    canceled_output_group,
)
from app.runtime.agent_life_service import AgentLifeService
from app.runtime.agent_state import AgentState
from app.runtime.autonomous_activity_execution import prepare_autonomous_execution
from app.runtime.autonomous_output import completed_speech_text
from app.runtime.behavior_planner import ActivityPlanValidator, BehaviorPlanner
from app.runtime.behavior_planning_context_builder import (
    BehaviorPlanningContextBuilder,
)
from app.runtime.buffered_event_dispatcher import BufferedEventDispatcher
from app.runtime.confirmation_coordinator import ConfirmationCoordinator
from app.runtime.conversation_input_recorder import ConversationInputRecorder
from app.runtime.event_buffer import EventBuffer
from app.runtime.event_dispatch_processor import EventDispatchProcessor
from app.runtime.event_filter import DefaultEventFilter, EventFilter
from app.runtime.event_ingress_processor import EventIngressProcessor
from app.runtime.event_prioritizer import DefaultEventPrioritizer, EventPrioritizer
from app.runtime.event_queue import EventQueue
from app.runtime.event_subscriber_registry import EventSubscriberRegistry
from app.runtime.event_type_router import EventTypeRouter
from app.runtime.explicit_activity_executor import ExplicitActivityExecutor
from app.runtime.ongoing_activity_coordinator import OngoingActivityCoordinator
from app.runtime.pending_confirmation import (
    ConfirmationResolver,
    PendingConfirmationManager,
)
from app.runtime.plugin_activity_coordinator import PluginActivityCoordinator
from app.runtime.plugin_ongoing_activity_synchronizer import (
    PluginOngoingActivitySynchronizer,
)
from app.runtime.runtime_diagnostic_snapshot_builder import (
    RuntimeDiagnosticSnapshotBuilder,
)
from app.runtime.user_input_event_logger import UserInputEventLogger
from app.runtime.user_input_event_router import UserInputEventRouter
from app.runtime.user_input_interruption_coordinator import (
    UserInputInterruptionCoordinator,
)
from app.shared.contracts.plugins.runtime import PluginCapability
from app.utils.conversation_log import ConversationLogger
from app.utils.trace import TraceLogger


class RuntimeCoordinator:
    """外部イベント処理と常駐 Thread の起動・停止を調停する中核。"""

    def __init__(
        self,
        event_queue: EventQueue,
        activity_manager: ActivityManager,
        action_planner: ActionPlanner,
        action_scheduler: ActionScheduler,
        activity_planning_request_queue: Queue[ActivityPlanningRequest],
        activity_planner_thread: ActivityPlannerThread,
        activity_executor_thread: ActivityExecutorThread,
        event_filter: EventFilter | None = None,
        event_prioritizer: EventPrioritizer | None = None,
        event_buffer: EventBuffer | None = None,
        agent_life_service: AgentLifeService | None = None,
        plugin_manager: PluginManager | None = None,
        behavior_planner: BehaviorPlanner | None = None,
        activity_plan_validator: ActivityPlanValidator | None = None,
        activity_registry: ActivityRegistry | None = None,
        pending_confirmation_manager: PendingConfirmationManager | None = None,
        confirmation_resolver: ConfirmationResolver | None = None,
        confirmation_coordinator: ConfirmationCoordinator | None = None,
        plugin_ongoing_activity_synchronizer: (
            PluginOngoingActivitySynchronizer | None
        ) = None,
        plugin_activity_coordinator: PluginActivityCoordinator | None = None,
        activity_switch_coordinator: ActivitySwitchCoordinator | None = None,
        autonomous_planning_enabled: bool = True,
        short_term_memory: ShortTermMemory | None = None,
        topic_history: TopicHistory | None = None,
        require_startup_completion: bool = False,
        async_initializers: tuple[Callable[[], Awaitable[None]], ...] = (),
        autonomous_planning_poll_seconds: float = 0.5,
        conversation_logger: ConversationLogger | None = None,
        conversation_input_recorder: ConversationInputRecorder | None = None,
        runtime_diagnostic_snapshot_builder: (
            RuntimeDiagnosticSnapshotBuilder | None
        ) = None,
        event_subscriber_registry: EventSubscriberRegistry | None = None,
        event_ingress_processor: EventIngressProcessor | None = None,
        event_dispatch_processor: EventDispatchProcessor | None = None,
        event_type_router: EventTypeRouter | None = None,
        behavior_planning_context_builder: (
            BehaviorPlanningContextBuilder | None
        ) = None,
        explicit_activity_executor: ExplicitActivityExecutor | None = None,
        user_input_interruption_coordinator: (
            UserInputInterruptionCoordinator | None
        ) = None,
        buffered_event_dispatcher: BufferedEventDispatcher | None = None,
        user_input_event_logger: UserInputEventLogger | None = None,
        user_input_event_router: UserInputEventRouter | None = None,
    ) -> None:
        self._event_queue = event_queue
        self._activity_manager = activity_manager
        self._action_planner = action_planner
        self._action_scheduler = action_scheduler
        self._activity_planning_request_queue = activity_planning_request_queue
        self._activity_planner_thread = activity_planner_thread
        self._activity_executor_thread = activity_executor_thread
        self._event_filter = event_filter or DefaultEventFilter()
        self._event_prioritizer = event_prioritizer or DefaultEventPrioritizer()
        self._event_buffer = event_buffer or EventBuffer()
        self._agent_life_service = agent_life_service or AgentLifeService(
            activity_manager
        )
        self._plugin_manager = plugin_manager
        self._runtime_diagnostic_snapshot_builder = (
            runtime_diagnostic_snapshot_builder
            or RuntimeDiagnosticSnapshotBuilder()
        )
        self._event_subscriber_registry = (
            event_subscriber_registry or EventSubscriberRegistry()
        )
        self._behavior_planner = behavior_planner
        self._activity_plan_validator = activity_plan_validator
        self._activity_registry = activity_registry
        self._pending_confirmation_manager = pending_confirmation_manager
        self._confirmation_resolver = confirmation_resolver or ConfirmationResolver()
        self._ongoing_activity_coordinator = OngoingActivityCoordinator(
            activity_manager
        )
        self._last_behavior_evaluation: ActivityPlanEvaluation | None = None
        self._last_behavior_fallback_plan: ActivityPlan | None = None
        self._running = False
        self._thread_join_timeout_seconds = 1.0
        self._trace_logger = TraceLogger()
        self._confirmation_coordinator = (
            confirmation_coordinator
            or (
                ConfirmationCoordinator(
                    manager=self._pending_confirmation_manager,
                    resolver=self._confirmation_resolver,
                    validator=self._activity_plan_validator,
                    conversation_fallback=self._with_plugin_availability,
                    plan_payload=self._plan_payload,
                    trace_logger=self._trace_logger,
                )
                if self._pending_confirmation_manager is not None
                and self._activity_plan_validator is not None
                else None
            )
        )
        self._plugin_ongoing_activity_synchronizer = (
            plugin_ongoing_activity_synchronizer
            or PluginOngoingActivitySynchronizer(
                ongoing_activity_coordinator=self._ongoing_activity_coordinator,
                trace_logger=self._trace_logger,
            )
        )
        self._user_input_event_logger = (
            user_input_event_logger
            or UserInputEventLogger(self._trace_logger)
        )
        self._user_input_event_router = (
            user_input_event_router
            or UserInputEventRouter(
                behavior_router=self._route_behavior,
                plugin_router=self._route_plugin_user_input,
                fallback=self._with_plugin_availability,
                behavior_routing_available=lambda: (
                    self._behavior_planner is not None
                    and self._activity_plan_validator is not None
                ),
                plugin_routing_available=lambda: self._has_plugin_capability(
                    PluginCapability.USER_INTENT_INTERPRETER.value
                ),
            )
        )
        self._buffered_event_dispatcher = (
            buffered_event_dispatcher
            or BufferedEventDispatcher(
                event_buffer=self._event_buffer,
                event_queue=self._event_queue,
                trace_logger=self._trace_logger,
            )
        )
        self._user_input_interruption_coordinator = (
            user_input_interruption_coordinator
            or UserInputInterruptionCoordinator(
                activity_manager=self._activity_manager,
                action_scheduler=self._action_scheduler,
                activity_planner_thread=self._activity_planner_thread,
                activity_executor_thread=self._activity_executor_thread,
                agent_life_service=self._agent_life_service,
                trace_logger=self._trace_logger,
            )
        )
        self._event_type_router = (
            event_type_router
            or EventTypeRouter(
                user_input_interruption_coordinator=(
                    self._user_input_interruption_coordinator
                ),
                user_input_event_logger=self._user_input_event_logger,
                user_input_event_router=self._user_input_event_router,
                behavior_router=self._route_behavior,
                behavior_routing_available=lambda: (
                    self._behavior_planner is not None
                    and self._activity_plan_validator is not None
                ),
            )
        )
        self._behavior_planning_context_builder = (
            behavior_planning_context_builder
            or (
                BehaviorPlanningContextBuilder(
                    activity_manager=self._activity_manager,
                    agent_life_service=self._agent_life_service,
                    plugin_manager=self._plugin_manager,
                    activity_registry=self._activity_registry,
                    short_term_memory=short_term_memory,
                    topic_history=topic_history,
                )
                if self._plugin_manager is not None
                else None
            )
        )
        self._explicit_activity_executor = (
            explicit_activity_executor
            or ExplicitActivityExecutor(
                activity_manager=self._activity_manager,
                action_planner=self._action_planner,
                action_scheduler=self._action_scheduler,
                agent_life_service=self._agent_life_service,
                trace_logger=self._trace_logger,
            )
        )
        self._plugin_activity_coordinator = (
            plugin_activity_coordinator
            or PluginActivityCoordinator(
                plugin_manager=self._plugin_manager,
                activity_plan_validator=self._activity_plan_validator,
                activity_manager=self._activity_manager,
                explicit_activity_executor=self._explicit_activity_executor,
                ongoing_synchronizer=(
                    self._plugin_ongoing_activity_synchronizer
                ),
                conversation_fallback=self._with_plugin_availability,
                execution_fallback=lambda event, contexts, reason, confidence: (
                    self._with_execution_fallback(
                        event,
                        contexts=contexts,
                        reason=reason,
                        confidence=confidence,
                    )
                ),
                ongoing_transition_payload=self._ongoing_transition_payload,
                trace_logger=self._trace_logger,
            )
        )
        self._activity_switch_coordinator = (
            activity_switch_coordinator
            or ActivitySwitchCoordinator(
                validator=self._activity_plan_validator,
                plugin_router=self._route_plugin_user_input,
                current_ongoing_activity=lambda: (
                    self._activity_manager.ongoing_activity
                ),
                execution_fallback=lambda event, contexts, reason, confidence: (
                    self._with_execution_fallback(
                        event,
                        contexts=contexts,
                        reason=reason,
                        confidence=confidence,
                    )
                ),
                trace_logger=self._trace_logger,
            )
        )
        self._event_dispatch_processor = (
            event_dispatch_processor
            or EventDispatchProcessor(
                event_prioritizer=self._event_prioritizer,
                activity_manager=self._activity_manager,
                user_input_interruption_coordinator=(
                    self._user_input_interruption_coordinator
                ),
                buffered_event_dispatcher=self._buffered_event_dispatcher,
                trace_logger=self._trace_logger,
            )
        )
        self._conversation_logger = conversation_logger or ConversationLogger()
        self._conversation_input_recorder = (
            conversation_input_recorder
            or ConversationInputRecorder(self._conversation_logger)
        )
        self._event_ingress_processor = (
            event_ingress_processor
            or EventIngressProcessor(
                event_filter=self._event_filter,
                activity_manager=self._activity_manager,
                conversation_input_recorder=self._conversation_input_recorder,
                agent_life_service=self._agent_life_service,
                event_subscriber_registry=self._event_subscriber_registry,
            )
        )
        self._event_enrichers: list[Callable[[AgentEvent], AgentEvent]] = []
        self._autonomous_planning_enabled = autonomous_planning_enabled
        self._short_term_memory = short_term_memory
        self._topic_history = topic_history
        self._startup_completed = not require_startup_completion
        self._async_initializers = async_initializers
        self._initializers_completed = False
        self._autonomous_planning_poll_seconds = max(
            autonomous_planning_poll_seconds, 0.05
        )
        self._last_autonomous_planning_request_at: float | None = None
        self._idle_sleep_seconds = 0.05

    @property
    def autonomous_planning_enabled(self) -> bool:
        return self._autonomous_planning_enabled

    @property
    def plugin_manager(self) -> PluginManager | None:
        return self._plugin_manager

    @property
    def activity_manager(self) -> ActivityManager:
        return self._activity_manager

    @property
    def agent_state(self) -> AgentState:
        """管理・診断用途のimmutableな現在状態スナップショット。"""

        return self._agent_life_service.agent_state

    def diagnostic_snapshot(self) -> dict[str, object]:
        """会話本文や外部秘密を含めず、Coreの現在状態を診断用に返す。"""

        return self._runtime_diagnostic_snapshot_builder.build(
            state=self._agent_life_service.agent_state,
            activity_manager=self._activity_manager,
            plugin_manager=self._plugin_manager,
        )

    @property
    def last_behavior_evaluation(self) -> ActivityPlanEvaluation | None:
        return self._last_behavior_evaluation

    @property
    def last_behavior_fallback_plan(self) -> ActivityPlan | None:
        return self._last_behavior_fallback_plan

    @property
    def pending_confirmation(self) -> PendingConfirmation | None:
        coordinator = self._confirmation_coordinator
        return coordinator.pending if coordinator is not None else None

    async def _execute_explicit_activity(self, activity: Activity) -> ActionPlanGroup:
        return await self._explicit_activity_executor.execute(activity)

    async def publish_event(self, event: AgentEvent) -> None:
        await self.publish_events([event])

    async def submit_user_text(
        self,
        text: str,
        *,
        source: str = "external",
        authority: InputAuthority = InputAuthority.USER,
    ) -> None:
        """本番入力AdapterからUSER_TEXTを共通ルーティングへ投入する公開入口。"""

        await self.publish_event(
            AgentEvent(
                event_type=AgentEventType.USER_TEXT,
                payload={"text": text, "source": source},
                authority=authority,
            )
        )

    async def execute_external_event(
        self, event: AgentEvent, *, missing_result_code: str = "activity_turn.missing"
    ) -> ActivityTurnResult:
        """Execute an outer-layer event through the shared Activity/Action pipeline."""

        group = await self._handle_event(event)
        base = group.activity_turn_result
        if base is None:
            raise RuntimeError(missing_result_code)
        return self._activity_manager.get_turn_result(base.activity_turn_id) or base

    async def execute_external_activity(self, activity: Activity) -> ActivityTurnResult:
        """Register and execute an Activity supplied through a Core contract."""

        registered = self._activity_manager.register_plugin_activity(activity)
        group = await self._execute_explicit_activity(registered)
        base = group.activity_turn_result
        if base is None:
            raise RuntimeError("activity_turn.missing")
        return self._activity_manager.get_turn_result(base.activity_turn_id) or base

    def cancel_outputs(self) -> bool:
        return self._action_scheduler.cancel_outputs()

    def configure_activity_policy(self, policy: object) -> None:
        """Install a policy through component-owned structural contracts."""

        gate = cast(Any, policy)
        self._activity_manager.set_activity_policy(gate)
        self._action_planner.set_activity_policy(gate)
        self._action_scheduler.set_activity_policy(gate)

    def subscribe_event(
        self,
        event_type: AgentEventType,
        handler: Callable[[AgentEvent], Awaitable[object]],
        *,
        predicate: Callable[[AgentEvent], bool] | None = None,
    ) -> None:
        self._event_subscriber_registry.register(
            event_type, handler, predicate=predicate
        )

    def register_event_enricher(
        self, enricher: Callable[[AgentEvent], AgentEvent]
    ) -> None:
        self._event_enrichers.append(enricher)

    async def publish_events(self, events: list[AgentEvent]) -> None:
        self._trace_logger.write(
            "runtime_coordinator:publish_events:start",
            event_count=len(events),
        )
        for event in events:
            ingress_result = await self._event_ingress_processor.process(event)
            filtered_event = ingress_result.event
            if filtered_event is None or ingress_result.consumed:
                continue
            foreground_at_receipt = ingress_result.foreground_at_receipt
            routed_event = await self._event_type_router.route(
                filtered_event,
                foreground_at_receipt=foreground_at_receipt,
            )
            if routed_event is None:
                continue
            filtered_event = routed_event
            self._event_dispatch_processor.process(
                original_event=event,
                routed_event=filtered_event,
                foreground_at_receipt=foreground_at_receipt,
            )

        await self._buffered_event_dispatcher.flush()

    def _has_plugin_capability(self, capability: str) -> bool:
        manager = self._plugin_manager
        return manager is not None and capability in manager.list_capabilities()

    async def _route_behavior(self, event: AgentEvent) -> AgentEvent | None:
        planner = self._behavior_planner
        validator = self._activity_plan_validator
        manager = self._plugin_manager
        if planner is None or validator is None or manager is None:
            return self._with_plugin_availability(event)
        context_builder = self._behavior_planning_context_builder
        if context_builder is None:
            return self._with_plugin_availability(event)
        preparation = context_builder.build(event)
        event = preparation.event
        planning_context = preparation.context
        ongoing = preparation.ongoing_activity
        situation_payload: dict[str, object]
        confirmation_payload: dict[str, object] = {}
        plan: ActivityPlan | None = None
        confirmation_coordinator = self._confirmation_coordinator
        if confirmation_coordinator is not None:
            confirmation = confirmation_coordinator.route_pending(
                event,
                planning_context,
            )
            if confirmation is not None:
                event = confirmation.event
                planning_context = confirmation.planning_context
                plan = confirmation.plan
                situation_payload = confirmation.situation_payload
                confirmation_payload = confirmation.confirmation_payload
                if confirmation.terminal_event is not None:
                    return confirmation.terminal_event
        if plan is None and event.event_type == AgentEventType.APP_STARTED:
            situation_payload = {
                "event_type": AgentEventType.APP_STARTED.value,
                "lifecycle_phase": "awakening",
                "speech_required": False,
            }
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
            if confirmation_coordinator is None:
                return self._with_plugin_availability(event)
            self._last_behavior_evaluation = validator.validate(plan)
            self._last_behavior_fallback_plan = None
            return confirmation_coordinator.request_confirmation(
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
        self._last_behavior_evaluation = evaluation
        self._last_behavior_fallback_plan = None
        self._trace_logger.info(
            "behavior_planner:activity_plan_evaluated",
            **event.trace_context.derive(
                behavior_plan_id=plan.behavior_plan_id
            ).as_log_fields(),
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
            "behavior_plan": self._plan_payload(plan),
            "behavior_plan_result": asdict(evaluation.result),
            "ongoing_transition": self._ongoing_transition_payload(
                plan,
                current_status=ongoing.status.value if ongoing is not None else None,
            ),
            **confirmation_payload,
            "trace_context": event.trace_context.derive(
                behavior_plan_id=plan.behavior_plan_id
            ),
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
            self._last_behavior_fallback_plan = fallback_plan
            behavior_payload["behavior_fallback_plan"] = self._plan_payload(
                fallback_plan
            )
            fallback_event = self._with_execution_fallback(
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
            routed = await self._route_activity_switch(event, plan, planning_context)
            if routed is None:
                return None
        elif plan.required_capability is not None:
            routed = await self._route_plugin_user_input(
                event,
                plugin_id=plan.provider_plugin_id,
                required_capability=plan.required_capability,
                activity_plan=plan,
            )
            if routed is None:
                return None
        else:
            routed = self._with_plugin_availability(event)
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

    async def _route_plugin_user_input(
        self,
        event: AgentEvent,
        *,
        plugin_id: str | None = None,
        required_capability: str | None = None,
        activity_plan: ActivityPlan | None = None,
    ) -> AgentEvent | None:
        return await self._plugin_activity_coordinator.route(
            event,
            plugin_id=plugin_id,
            required_capability=required_capability,
            activity_plan=activity_plan,
        )

    @staticmethod
    def _plan_payload(plan: ActivityPlan) -> dict[str, object]:
        payload = asdict(plan)
        payload["decision"] = plan.decision.value
        payload["operation"] = plan.operation.value if plan.operation else None
        payload["speech_act"] = plan.speech_act.value
        payload["ongoing_input_decision"] = (
            plan.ongoing_input_decision.value
            if plan.ongoing_input_decision is not None
            else None
        )
        return payload

    async def _route_activity_switch(
        self,
        event: AgentEvent,
        plan: ActivityPlan,
        planning_context: BehaviorPlanningContext,
    ) -> AgentEvent | None:
        return await self._activity_switch_coordinator.route(
            event,
            plan,
            planning_context,
            plugin_router=self._route_plugin_user_input,
        )

    @staticmethod
    def _ongoing_transition_payload(
        plan: ActivityPlan | None,
        *,
        current_status: str | None,
        stopped: bool = False,
        transition_result: str | None = None,
    ) -> dict[str, object]:
        if plan is None:
            return {}
        return {
            "ongoing_input_decision": (
                plan.ongoing_input_decision.value
                if plan.ongoing_input_decision is not None
                else None
            ),
            "current_activity_status": current_status,
            "current_activity_preserved": plan.current_activity_preserved
            and not stopped,
            "current_activity_paused": plan.current_activity_paused,
            "current_activity_stopped": stopped,
            "requested_new_activity": plan.requested_new_activity,
            "transition_result": transition_result,
        }

    def _with_plugin_availability(self, event: AgentEvent) -> AgentEvent:
        capabilities = (
            sorted(self._plugin_manager.list_capabilities())
            if self._plugin_manager is not None
            else []
        )
        interpretation = interpret_user_request(str(event.payload.get("text") or ""))
        if interpretation.kind == UserRequestKind.EXECUTION:
            self._trace_logger.info(
                "runtime_coordinator:execution_request_unmatched",
                confidence=interpretation.confidence,
                reason=interpretation.reason,
                available_capability_count=len(capabilities),
            )
            return self._with_execution_fallback(
                event,
                contexts=[],
                reason=interpretation.reason,
                confidence=interpretation.confidence,
            )
        return replace(
            event,
            payload={
                **event.payload,
                "available_plugin_capabilities": capabilities,
                "user_request_kind": interpretation.kind.value,
                "execution_performed": False,
            },
        )

    def _with_execution_fallback(
        self,
        event: AgentEvent,
        *,
        contexts: list[dict[str, object]],
        reason: str,
        confidence: float,
    ) -> AgentEvent:
        capabilities = (
            sorted(self._plugin_manager.list_capabilities())
            if self._plugin_manager is not None
            else []
        )
        self._trace_logger.info(
            "runtime_coordinator:conversation_fallback_selected",
            reason=reason,
            confidence=confidence,
            available_capability_count=len(capabilities),
        )
        return replace(
            event,
            payload={
                **event.payload,
                "available_plugin_capabilities": capabilities,
                "plugin_contexts": contexts,
                "user_request_kind": UserRequestKind.EXECUTION.value,
                "execution_request_unmatched": True,
                "execution_performed": False,
                "execution_match_confidence": confidence,
                "execution_match_reason": reason,
                "safe_conversation_fallback": "今はそれを一緒にできないんだ。別のお話をしよう。",
                "available_alternative": "文字での通常会話",
            },
        )

    async def run_once(self) -> ActionPlanGroup | None:
        self._trace_logger.write(
            "runtime_coordinator:run_once:start",
            queue_empty=self._event_queue.empty(),
            drive_curiosity=self._agent_life_service.agent_state.current_drive.curiosity,
            drive_engagement=self._agent_life_service.agent_state.current_drive.engagement,
            drive_boredom=self._agent_life_service.agent_state.current_drive.boredom,
            drive_energy=self._agent_life_service.agent_state.current_drive.energy,
        )
        if self._event_queue.empty():
            if not self._autonomous_planning_enabled:
                self._trace_logger.write(
                    "runtime_coordinator:run_once:autonomous_planning_disabled"
                )
                return None
            if not self._startup_completed:
                return None
            now = monotonic()
            request_recently_sent = (
                self._last_autonomous_planning_request_at is not None
                and now - self._last_autonomous_planning_request_at
                < self._autonomous_planning_poll_seconds
            )
            if (
                request_recently_sent
                or not self._activity_planning_request_queue.empty()
                or self._activity_planner_thread.is_busy
            ):
                return None
            self._activity_planning_request_queue.put(ActivityPlanningRequest())
            self._last_autonomous_planning_request_at = now
            self._trace_logger.write(
                "runtime_coordinator:run_once:activity_planning_requested",
                request_queue_size=self._activity_planning_request_queue.qsize(),
            )
            self._trace_logger.write("runtime_coordinator:run_once:no_event")
            return None

        event = await self._event_queue.get()
        self._trace_logger.write(
            "runtime_coordinator:run_once:queue_get",
            level=(
                "DEBUG"
                if self._is_agent_state_only_event(event) or event.discardable
                else "INFO"
            ),
            event_type=event.event_type.value,
            event_id=event.event_id,
            priority=event.priority,
            discardable=event.discardable,
            replace_key=event.replace_key,
        )
        result = await self._handle_event(event)
        if event.event_type == AgentEventType.APP_STARTED:
            self._startup_completed = True
            self._agent_life_service.record_awakening_completed()
            self._trace_logger.info(
                "runtime_coordinator:startup_completed",
                source_event_id=event.event_id,
            )
        return result

    async def run(self) -> None:
        self._running = True
        self._trace_logger.info("runtime_coordinator:run:start")

        await self._run_async_initializers()
        self._start_threads()

        while self._running:
            action_plan_group = await self.run_once()
            if action_plan_group is None:
                self._trace_logger.write("runtime_coordinator:run:idle_sleep")
                await asyncio.sleep(self._idle_sleep_seconds)

    async def _run_async_initializers(self) -> None:
        if self._initializers_completed:
            return
        for initializer in self._async_initializers:
            try:
                await initializer()
            except Exception as error:
                self._trace_logger.error(
                    "runtime_coordinator:async_initializer_failed",
                    initializer=getattr(initializer, "__qualname__", type(initializer).__name__),
                    error_type=type(error).__name__,
                    error_message=str(error),
                )
        self._initializers_completed = True

    def stop(self) -> None:
        self._trace_logger.info("runtime_coordinator:stop")
        self._running = False
        self._stop_threads()
        if self._plugin_manager is not None:
            self._plugin_manager.shutdown_plugins()
        self._ongoing_activity_coordinator.cancel(reason="runtime_stopped")

    def _start_threads(self) -> None:
        """常駐 Thread を必要に応じて起動する。"""

        if not self._autonomous_planning_enabled:
            self._trace_logger.info(
                "runtime_coordinator:threads:skipped",
                reason="autonomous_planning_disabled",
            )
            return

        if not self._activity_planner_thread.is_alive():
            self._activity_planner_thread.start()

        if not self._activity_executor_thread.is_alive():
            self._activity_executor_thread.start()

        self._trace_logger.info(
            "runtime_coordinator:threads:start",
            activity_planner_thread_alive=self._activity_planner_thread.is_alive(),
            activity_executor_thread_alive=self._activity_executor_thread.is_alive(),
        )

    def _stop_threads(self) -> None:
        """常駐 Thread に停止要求を送り、終了を待つ。"""

        if not self._autonomous_planning_enabled:
            return

        self._activity_planner_thread.stop()
        self._activity_executor_thread.stop()

        if self._activity_planner_thread.is_alive():
            self._activity_planner_thread.join(
                timeout=self._thread_join_timeout_seconds
            )

        if self._activity_executor_thread.is_alive():
            self._activity_executor_thread.join(
                timeout=self._thread_join_timeout_seconds
            )

        self._trace_logger.info(
            "runtime_coordinator:threads:stopped",
            activity_planner_thread_alive=self._activity_planner_thread.is_alive(),
            activity_executor_thread_alive=self._activity_executor_thread.is_alive(),
        )

    async def _handle_event(self, event: AgentEvent) -> ActionPlanGroup:
        for enricher in self._event_enrichers:
            event = enricher(event)
        self._agent_life_service.handle_event(event)
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
            situation = (
                self._agent_life_service.agent_state.current_situation.as_context()
            )
            event = replace(
                event,
                payload={
                    **event.payload,
                    "situation": situation,
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
            self._trace_logger.write(
                "runtime_coordinator:handle_event:state_only",
                event_type=event.event_type.value,
                drive_curiosity=self._agent_life_service.agent_state.current_drive.curiosity,
                drive_engagement=self._agent_life_service.agent_state.current_drive.engagement,
                drive_boredom=self._agent_life_service.agent_state.current_drive.boredom,
                drive_energy=self._agent_life_service.agent_state.current_drive.energy,
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
        self._trace_logger.write(
            "runtime_coordinator:handle_event:agent_state_updated",
            drive_curiosity=self._agent_life_service.agent_state.current_drive.curiosity,
            drive_engagement=self._agent_life_service.agent_state.current_drive.engagement,
            drive_boredom=self._agent_life_service.agent_state.current_drive.boredom,
            drive_energy=self._agent_life_service.agent_state.current_drive.energy,
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
                    action.action_type.value
                    for action in action_plan_group.action_plans
                ],
                source_activity_ids=[
                    action.source_activity_id
                    for action in action_plan_group.action_plans
                ],
                reason="activity_suspended_before_action_execution",
            )
            canceled_group = canceled_output_group(
                action_plan_group, reason="activity_suspended_before_action_execution"
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
                action_plan_group.activity_turn_result, output_result
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
        self._trace_logger.write(
            "runtime_coordinator:handle_event:agent_state_synced_after_activity_complete",
            active_activity_exists=self._agent_life_service.agent_state.active_activity
            is not None,
            pending_activity_count=len(
                self._agent_life_service.agent_state.pending_activities
            ),
            suspended_activity_count=len(
                self._agent_life_service.agent_state.suspended_activities
            ),
        )
        return action_plan_group

    def _is_agent_state_only_event(self, event: AgentEvent) -> bool:
        return event.event_type in (
            AgentEventType.SPEECH_STARTED,
            AgentEventType.SPEECH_FINISHED,
        )
