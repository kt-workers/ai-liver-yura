from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from queue import Queue

from app.core.plugins import PluginManager
from app.domain.actions import ActionPlanGroup
from app.domain.activities import OngoingActivity
from app.domain.events import AgentEvent
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
from app.runtime.activity_switch_coordinator import ActivitySwitchCoordinator
from app.runtime.agent_life_service import AgentLifeService
from app.runtime.behavior_planner import ActivityPlanValidator, BehaviorPlanner
from app.runtime.behavior_planning_context_builder import (
    BehaviorPlanningContextBuilder,
)
from app.runtime.behavior_routing_coordinator import BehaviorRoutingCoordinator
from app.runtime.behavior_routing_support import (
    BehaviorFallbackRouter,
    ongoing_transition_payload,
    plan_payload,
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
from app.runtime.interaction_reaction_policy import InteractionReactionPolicy
from app.runtime.ongoing_activity_coordinator import OngoingActivityCoordinator
from app.runtime.pending_confirmation import (
    ConfirmationResolver,
    PendingConfirmationManager,
)
from app.runtime.plugin_activity_coordinator import PluginActivityCoordinator
from app.runtime.plugin_ongoing_activity_synchronizer import (
    PluginOngoingActivitySynchronizer,
)
from app.runtime.runtime_event_executor import RuntimeEventExecutor
from app.runtime.runtime_host_controller import RuntimeHostController
from app.runtime.runtime_loop import RuntimeLoop
from app.runtime.user_input_event_logger import UserInputEventLogger
from app.runtime.user_input_event_router import (
    AsyncEventRouter,
    AvailabilityCheck,
    EventFallback,
    UserInputEventRouter,
)
from app.runtime.user_input_interruption_coordinator import (
    UserInputInterruptionCoordinator,
)
from app.utils.conversation_log import ConversationLogger
from app.utils.trace import TraceLogger


@dataclass(frozen=True, slots=True)
class RuntimeExecutionComposition:
    """RuntimeCoordinatorが保持する実行系コンポーネント群。"""

    event_executor: RuntimeEventExecutor
    runtime_loop: RuntimeLoop
    host_controller: RuntimeHostController


@dataclass(frozen=True, slots=True)
class RuntimeEventPipelineComposition:
    """RuntimeCoordinatorが保持するEvent受付・入力経路のコンポーネント群。"""

    event_filter: EventFilter
    event_prioritizer: EventPrioritizer
    event_buffer: EventBuffer
    event_subscriber_registry: EventSubscriberRegistry
    user_input_event_logger: UserInputEventLogger
    user_input_event_router: UserInputEventRouter
    buffered_event_dispatcher: BufferedEventDispatcher
    user_input_interruption_coordinator: UserInputInterruptionCoordinator
    event_type_router: EventTypeRouter
    event_dispatch_processor: EventDispatchProcessor
    conversation_logger: ConversationLogger
    conversation_input_recorder: ConversationInputRecorder
    event_ingress_processor: EventIngressProcessor


@dataclass(frozen=True, slots=True)
class RuntimeBehaviorComposition:
    """RuntimeCoordinatorが保持するBehavior・Plugin系コンポーネント群。"""

    confirmation_resolver: ConfirmationResolver
    ongoing_activity_coordinator: OngoingActivityCoordinator
    behavior_fallback_router: BehaviorFallbackRouter
    confirmation_coordinator: ConfirmationCoordinator | None
    plugin_ongoing_activity_synchronizer: PluginOngoingActivitySynchronizer
    behavior_planning_context_builder: BehaviorPlanningContextBuilder | None
    explicit_activity_executor: ExplicitActivityExecutor
    plugin_activity_coordinator: PluginActivityCoordinator
    activity_switch_coordinator: ActivitySwitchCoordinator
    behavior_routing_coordinator: BehaviorRoutingCoordinator


class RuntimeCompositionRoot:
    """Runtimeコンポーネントの生成順序と依存配線を一箇所へ閉じ込める。"""

    def build_behavior_composition(
        self,
        *,
        activity_manager: ActivityManager,
        action_planner: ActionPlanner,
        action_scheduler: ActionScheduler,
        agent_life_service: AgentLifeService,
        plugin_manager: PluginManager | None,
        behavior_planner: BehaviorPlanner | None,
        activity_plan_validator: ActivityPlanValidator | None,
        activity_registry: ActivityRegistry | None,
        pending_confirmation_manager: PendingConfirmationManager | None,
        short_term_memory: ShortTermMemory | None,
        topic_history: TopicHistory | None,
        trace_logger: TraceLogger,
        plugin_router: Callable[..., Awaitable[AgentEvent | None]],
        execution_fallback: Callable[
            [AgentEvent, list[dict[str, object]], str, float],
            AgentEvent,
        ],
        current_ongoing_activity: Callable[[], OngoingActivity | None],
        confirmation_resolver: ConfirmationResolver | None = None,
        confirmation_coordinator: ConfirmationCoordinator | None = None,
        plugin_ongoing_activity_synchronizer: (
            PluginOngoingActivitySynchronizer | None
        ) = None,
        behavior_planning_context_builder: (
            BehaviorPlanningContextBuilder | None
        ) = None,
        explicit_activity_executor: ExplicitActivityExecutor | None = None,
        plugin_activity_coordinator: PluginActivityCoordinator | None = None,
        activity_switch_coordinator: ActivitySwitchCoordinator | None = None,
        behavior_routing_coordinator: BehaviorRoutingCoordinator | None = None,
    ) -> RuntimeBehaviorComposition:
        resolved_confirmation_resolver = (
            confirmation_resolver
            if confirmation_resolver is not None
            else ConfirmationResolver()
        )
        resolved_ongoing_activity_coordinator = OngoingActivityCoordinator(
            activity_manager
        )
        resolved_behavior_fallback_router = BehaviorFallbackRouter(
            plugin_manager=plugin_manager,
            trace_logger=trace_logger,
        )
        resolved_confirmation_coordinator = (
            confirmation_coordinator
            if confirmation_coordinator is not None
            else (
                ConfirmationCoordinator(
                    manager=pending_confirmation_manager,
                    resolver=resolved_confirmation_resolver,
                    validator=activity_plan_validator,
                    conversation_fallback=(
                        resolved_behavior_fallback_router.with_plugin_availability
                    ),
                    plan_payload=plan_payload,
                    trace_logger=trace_logger,
                )
                if pending_confirmation_manager is not None
                and activity_plan_validator is not None
                else None
            )
        )
        resolved_plugin_ongoing_activity_synchronizer = (
            plugin_ongoing_activity_synchronizer
            if plugin_ongoing_activity_synchronizer is not None
            else PluginOngoingActivitySynchronizer(
                ongoing_activity_coordinator=(
                    resolved_ongoing_activity_coordinator
                ),
                trace_logger=trace_logger,
            )
        )
        resolved_behavior_planning_context_builder = (
            behavior_planning_context_builder
            if behavior_planning_context_builder is not None
            else (
                BehaviorPlanningContextBuilder(
                    activity_manager=activity_manager,
                    agent_life_service=agent_life_service,
                    plugin_manager=plugin_manager,
                    activity_registry=activity_registry,
                    short_term_memory=short_term_memory,
                    topic_history=topic_history,
                )
                if plugin_manager is not None
                else None
            )
        )
        resolved_explicit_activity_executor = (
            explicit_activity_executor
            if explicit_activity_executor is not None
            else ExplicitActivityExecutor(
                activity_manager=activity_manager,
                action_planner=action_planner,
                action_scheduler=action_scheduler,
                agent_life_service=agent_life_service,
                trace_logger=trace_logger,
            )
        )
        resolved_plugin_activity_coordinator = (
            plugin_activity_coordinator
            if plugin_activity_coordinator is not None
            else PluginActivityCoordinator(
                plugin_manager=plugin_manager,
                activity_plan_validator=activity_plan_validator,
                activity_manager=activity_manager,
                explicit_activity_executor=resolved_explicit_activity_executor,
                ongoing_synchronizer=(
                    resolved_plugin_ongoing_activity_synchronizer
                ),
                conversation_fallback=(
                    resolved_behavior_fallback_router.with_plugin_availability
                ),
                execution_fallback=execution_fallback,
                ongoing_transition_payload=ongoing_transition_payload,
                trace_logger=trace_logger,
            )
        )
        resolved_activity_switch_coordinator = (
            activity_switch_coordinator
            if activity_switch_coordinator is not None
            else ActivitySwitchCoordinator(
                validator=activity_plan_validator,
                plugin_router=plugin_router,
                current_ongoing_activity=current_ongoing_activity,
                execution_fallback=execution_fallback,
                trace_logger=trace_logger,
            )
        )
        resolved_behavior_routing_coordinator = (
            behavior_routing_coordinator
            if behavior_routing_coordinator is not None
            else BehaviorRoutingCoordinator(
                planner=behavior_planner,
                validator=activity_plan_validator,
                plugin_manager=plugin_manager,
                context_builder=resolved_behavior_planning_context_builder,
                confirmation_coordinator=resolved_confirmation_coordinator,
                plugin_activity_coordinator=resolved_plugin_activity_coordinator,
                activity_switch_coordinator=resolved_activity_switch_coordinator,
                fallback_router=resolved_behavior_fallback_router,
                trace_logger=trace_logger,
            )
        )
        return RuntimeBehaviorComposition(
            confirmation_resolver=resolved_confirmation_resolver,
            ongoing_activity_coordinator=resolved_ongoing_activity_coordinator,
            behavior_fallback_router=resolved_behavior_fallback_router,
            confirmation_coordinator=resolved_confirmation_coordinator,
            plugin_ongoing_activity_synchronizer=(
                resolved_plugin_ongoing_activity_synchronizer
            ),
            behavior_planning_context_builder=(
                resolved_behavior_planning_context_builder
            ),
            explicit_activity_executor=resolved_explicit_activity_executor,
            plugin_activity_coordinator=resolved_plugin_activity_coordinator,
            activity_switch_coordinator=resolved_activity_switch_coordinator,
            behavior_routing_coordinator=resolved_behavior_routing_coordinator,
        )

    def build_event_pipeline(
        self,
        *,
        event_queue: EventQueue,
        activity_manager: ActivityManager,
        action_scheduler: ActionScheduler,
        activity_planner_thread: ActivityPlannerThread,
        activity_executor_thread: ActivityExecutorThread,
        agent_life_service: AgentLifeService,
        trace_logger: TraceLogger,
        behavior_router: AsyncEventRouter,
        plugin_router: AsyncEventRouter,
        fallback_router: EventFallback,
        behavior_routing_available: AvailabilityCheck,
        plugin_routing_available: AvailabilityCheck,
        event_filter: EventFilter | None = None,
        event_prioritizer: EventPrioritizer | None = None,
        event_buffer: EventBuffer | None = None,
        event_subscriber_registry: EventSubscriberRegistry | None = None,
        user_input_event_logger: UserInputEventLogger | None = None,
        user_input_event_router: UserInputEventRouter | None = None,
        buffered_event_dispatcher: BufferedEventDispatcher | None = None,
        user_input_interruption_coordinator: (
            UserInputInterruptionCoordinator | None
        ) = None,
        event_type_router: EventTypeRouter | None = None,
        event_dispatch_processor: EventDispatchProcessor | None = None,
        conversation_logger: ConversationLogger | None = None,
        conversation_input_recorder: ConversationInputRecorder | None = None,
        event_ingress_processor: EventIngressProcessor | None = None,
    ) -> RuntimeEventPipelineComposition:
        resolved_event_filter = (
            event_filter if event_filter is not None else DefaultEventFilter()
        )
        resolved_event_prioritizer = (
            event_prioritizer
            if event_prioritizer is not None
            else DefaultEventPrioritizer()
        )
        resolved_event_buffer = (
            event_buffer if event_buffer is not None else EventBuffer()
        )
        resolved_event_subscriber_registry = (
            event_subscriber_registry
            if event_subscriber_registry is not None
            else EventSubscriberRegistry()
        )
        resolved_user_input_event_logger = (
            user_input_event_logger
            if user_input_event_logger is not None
            else UserInputEventLogger(trace_logger)
        )
        resolved_user_input_event_router = (
            user_input_event_router
            if user_input_event_router is not None
            else UserInputEventRouter(
                behavior_router=behavior_router,
                plugin_router=plugin_router,
                fallback=fallback_router,
                behavior_routing_available=behavior_routing_available,
                plugin_routing_available=plugin_routing_available,
            )
        )
        resolved_buffered_event_dispatcher = (
            buffered_event_dispatcher
            if buffered_event_dispatcher is not None
            else BufferedEventDispatcher(
                event_buffer=resolved_event_buffer,
                event_queue=event_queue,
                trace_logger=trace_logger,
            )
        )
        resolved_user_input_interruption_coordinator = (
            user_input_interruption_coordinator
            if user_input_interruption_coordinator is not None
            else UserInputInterruptionCoordinator(
                activity_manager=activity_manager,
                action_scheduler=action_scheduler,
                activity_planner_thread=activity_planner_thread,
                activity_executor_thread=activity_executor_thread,
                agent_life_service=agent_life_service,
                trace_logger=trace_logger,
            )
        )
        resolved_event_type_router = (
            event_type_router
            if event_type_router is not None
            else EventTypeRouter(
                user_input_interruption_coordinator=(
                    resolved_user_input_interruption_coordinator
                ),
                user_input_event_logger=resolved_user_input_event_logger,
                user_input_event_router=resolved_user_input_event_router,
                behavior_router=behavior_router,
                behavior_routing_available=behavior_routing_available,
            )
        )
        resolved_event_dispatch_processor = (
            event_dispatch_processor
            if event_dispatch_processor is not None
            else EventDispatchProcessor(
                event_prioritizer=resolved_event_prioritizer,
                activity_manager=activity_manager,
                user_input_interruption_coordinator=(
                    resolved_user_input_interruption_coordinator
                ),
                buffered_event_dispatcher=resolved_buffered_event_dispatcher,
                trace_logger=trace_logger,
            )
        )
        resolved_conversation_logger = (
            conversation_logger
            if conversation_logger is not None
            else ConversationLogger()
        )
        resolved_conversation_input_recorder = (
            conversation_input_recorder
            if conversation_input_recorder is not None
            else ConversationInputRecorder(resolved_conversation_logger)
        )
        resolved_event_ingress_processor = (
            event_ingress_processor
            if event_ingress_processor is not None
            else EventIngressProcessor(
                event_filter=resolved_event_filter,
                activity_manager=activity_manager,
                conversation_input_recorder=resolved_conversation_input_recorder,
                agent_life_service=agent_life_service,
                event_subscriber_registry=resolved_event_subscriber_registry,
            )
        )
        return RuntimeEventPipelineComposition(
            event_filter=resolved_event_filter,
            event_prioritizer=resolved_event_prioritizer,
            event_buffer=resolved_event_buffer,
            event_subscriber_registry=resolved_event_subscriber_registry,
            user_input_event_logger=resolved_user_input_event_logger,
            user_input_event_router=resolved_user_input_event_router,
            buffered_event_dispatcher=resolved_buffered_event_dispatcher,
            user_input_interruption_coordinator=(
                resolved_user_input_interruption_coordinator
            ),
            event_type_router=resolved_event_type_router,
            event_dispatch_processor=resolved_event_dispatch_processor,
            conversation_logger=resolved_conversation_logger,
            conversation_input_recorder=resolved_conversation_input_recorder,
            event_ingress_processor=resolved_event_ingress_processor,
        )

    def build_execution(
        self,
        *,
        event_queue: EventQueue,
        activity_manager: ActivityManager,
        action_planner: ActionPlanner,
        action_scheduler: ActionScheduler,
        activity_planning_request_queue: Queue[ActivityPlanningRequest],
        activity_planner_thread: ActivityPlannerThread,
        activity_executor_thread: ActivityExecutorThread,
        agent_life_service: AgentLifeService,
        plugin_manager: PluginManager | None,
        ongoing_activity_coordinator: OngoingActivityCoordinator,
        event_handler: Callable[[AgentEvent], Awaitable[ActionPlanGroup]],
        event_enrichers_provider: Callable[
            [], tuple[Callable[[AgentEvent], AgentEvent], ...]
        ],
        autonomous_planning_enabled: bool,
        require_startup_completion: bool,
        autonomous_planning_poll_seconds: float,
        async_initializers: tuple[Callable[[], Awaitable[None]], ...],
        trace_logger: TraceLogger,
        interaction_reaction_policy: InteractionReactionPolicy | None,
        event_executor: RuntimeEventExecutor | None = None,
        runtime_loop: RuntimeLoop | None = None,
        host_controller: RuntimeHostController | None = None,
    ) -> RuntimeExecutionComposition:
        resolved_event_executor = event_executor or RuntimeEventExecutor(
            activity_manager=activity_manager,
            action_planner=action_planner,
            action_scheduler=action_scheduler,
            agent_life_service=agent_life_service,
            event_enrichers_provider=event_enrichers_provider,
            trace_logger=trace_logger,
            interaction_reaction_policy=interaction_reaction_policy,
        )
        resolved_runtime_loop = runtime_loop or RuntimeLoop(
            event_queue=event_queue,
            activity_planning_request_queue=activity_planning_request_queue,
            activity_planner_thread=activity_planner_thread,
            agent_life_service=agent_life_service,
            event_handler=event_handler,
            autonomous_planning_enabled=autonomous_planning_enabled,
            require_startup_completion=require_startup_completion,
            autonomous_planning_poll_seconds=autonomous_planning_poll_seconds,
            trace_logger=trace_logger,
        )
        resolved_host_controller = host_controller or RuntimeHostController(
            runtime_loop=resolved_runtime_loop,
            activity_planner_thread=activity_planner_thread,
            activity_executor_thread=activity_executor_thread,
            plugin_manager=plugin_manager,
            ongoing_activity_coordinator=ongoing_activity_coordinator,
            async_initializers=async_initializers,
            trace_logger=trace_logger,
        )
        return RuntimeExecutionComposition(
            event_executor=resolved_event_executor,
            runtime_loop=resolved_runtime_loop,
            host_controller=resolved_host_controller,
        )
