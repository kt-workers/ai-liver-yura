from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from queue import Queue

from app.core.plugins import PluginManager
from app.domain.actions import ActionPlanGroup
from app.domain.events import AgentEvent
from app.runtime.action_planner import ActionPlanner
from app.runtime.action_scheduler import ActionScheduler
from app.runtime.activity_executor_thread import ActivityExecutorThread
from app.runtime.activity_manager import ActivityManager
from app.runtime.activity_planner_thread import (
    ActivityPlannerThread,
    ActivityPlanningRequest,
)
from app.runtime.agent_life_service import AgentLifeService
from app.runtime.event_queue import EventQueue
from app.runtime.interaction_reaction_policy import InteractionReactionPolicy
from app.runtime.ongoing_activity_coordinator import OngoingActivityCoordinator
from app.runtime.runtime_event_executor import RuntimeEventExecutor
from app.runtime.runtime_host_controller import RuntimeHostController
from app.runtime.runtime_loop import RuntimeLoop
from app.utils.trace import TraceLogger


@dataclass(frozen=True, slots=True)
class RuntimeExecutionComposition:
    """RuntimeCoordinatorが保持する実行系コンポーネント群。"""

    event_executor: RuntimeEventExecutor
    runtime_loop: RuntimeLoop
    host_controller: RuntimeHostController


class RuntimeCompositionRoot:
    """Runtime実行系の生成順序と依存配線を一箇所へ閉じ込める。"""

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
