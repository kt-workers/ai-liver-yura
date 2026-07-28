from __future__ import annotations

from collections.abc import Awaitable, Callable
from queue import Queue
from time import monotonic

from app.domain.actions import ActionPlanGroup
from app.domain.events import AgentEvent, AgentEventType
from app.runtime.activity_planner_thread import (
    ActivityPlannerThread,
    ActivityPlanningRequest,
)
from app.runtime.agent_life_service import AgentLifeService
from app.runtime.event_queue import EventQueue
from app.utils.trace import TraceLogger


class RuntimeLoop:
    """Event取得と自律計画要求の周期制御を所有する。"""

    def __init__(
        self,
        *,
        event_queue: EventQueue,
        activity_planning_request_queue: Queue[ActivityPlanningRequest],
        activity_planner_thread: ActivityPlannerThread,
        agent_life_service: AgentLifeService,
        event_handler: Callable[[AgentEvent], Awaitable[ActionPlanGroup]],
        autonomous_planning_enabled: bool,
        require_startup_completion: bool,
        autonomous_planning_poll_seconds: float,
        trace_logger: TraceLogger,
        monotonic_clock: Callable[[], float] = monotonic,
    ) -> None:
        self._event_queue = event_queue
        self._request_queue = activity_planning_request_queue
        self._planner_thread = activity_planner_thread
        self._agent_life_service = agent_life_service
        self._event_handler = event_handler
        self._autonomous_planning_enabled = autonomous_planning_enabled
        self._startup_completed = not require_startup_completion
        self._poll_seconds = max(autonomous_planning_poll_seconds, 0.05)
        self._trace_logger = trace_logger
        self._monotonic = monotonic_clock
        self._last_planning_request_at: float | None = None

    @property
    def autonomous_planning_enabled(self) -> bool:
        return self._autonomous_planning_enabled

    @property
    def startup_completed(self) -> bool:
        return self._startup_completed

    async def run_once(self) -> ActionPlanGroup | None:
        state = self._agent_life_service.agent_state
        self._trace_logger.write(
            "runtime_coordinator:run_once:start",
            queue_empty=self._event_queue.empty(),
            drive_curiosity=state.current_drive.curiosity,
            drive_engagement=state.current_drive.engagement,
            drive_boredom=state.current_drive.boredom,
            drive_energy=state.current_drive.energy,
        )
        if self._event_queue.empty():
            self._request_autonomous_planning_if_due()
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
        result = await self._event_handler(event)
        if event.event_type == AgentEventType.APP_STARTED:
            self._startup_completed = True
            self._agent_life_service.record_awakening_completed()
            self._trace_logger.info(
                "runtime_coordinator:startup_completed",
                source_event_id=event.event_id,
            )
        return result

    def _request_autonomous_planning_if_due(self) -> None:
        if not self._autonomous_planning_enabled:
            self._trace_logger.write(
                "runtime_coordinator:run_once:autonomous_planning_disabled"
            )
            return
        if not self._startup_completed:
            return
        now = self._monotonic()
        request_recently_sent = (
            self._last_planning_request_at is not None
            and now - self._last_planning_request_at < self._poll_seconds
        )
        if (
            request_recently_sent
            or not self._request_queue.empty()
            or self._planner_thread.is_busy
        ):
            return
        self._request_queue.put(ActivityPlanningRequest())
        self._last_planning_request_at = now
        self._trace_logger.write(
            "runtime_coordinator:run_once:activity_planning_requested",
            request_queue_size=self._request_queue.qsize(),
        )
        self._trace_logger.write("runtime_coordinator:run_once:no_event")

    @staticmethod
    def _is_agent_state_only_event(event: AgentEvent) -> bool:
        return event.event_type in (
            AgentEventType.SPEECH_STARTED,
            AgentEventType.SPEECH_FINISHED,
        )
