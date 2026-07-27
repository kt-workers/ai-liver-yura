from queue import Queue

import pytest

from app.domain.actions import ActionPlanGroup
from app.domain.events import AgentEvent, AgentEventType
from app.runtime.activity_manager import ActivityManager
from app.runtime.activity_planner_thread import ActivityPlanningRequest
from app.runtime.agent_life_service import AgentLifeService
from app.runtime.event_queue import EventQueue
from app.runtime.runtime_loop import RuntimeLoop
from app.utils.trace import TraceLogger

pytestmark = pytest.mark.unit


class FakePlannerThread:
    def __init__(self, *, busy: bool = False) -> None:
        self.is_busy = busy


def _loop(
    *,
    enabled: bool = True,
    require_startup: bool = False,
    busy: bool = False,
    clock: list[float] | None = None,
) -> tuple[RuntimeLoop, EventQueue, Queue[ActivityPlanningRequest]]:
    event_queue = EventQueue()
    request_queue: Queue[ActivityPlanningRequest] = Queue()
    agent_life = AgentLifeService(ActivityManager())

    async def handle(_event: AgentEvent) -> ActionPlanGroup:
        return ActionPlanGroup()

    times = clock or [0.0]
    runtime_loop = RuntimeLoop(
        event_queue=event_queue,
        activity_planning_request_queue=request_queue,
        activity_planner_thread=FakePlannerThread(busy=busy),  # type: ignore[arg-type]
        agent_life_service=agent_life,
        event_handler=handle,
        autonomous_planning_enabled=enabled,
        require_startup_completion=require_startup,
        autonomous_planning_poll_seconds=0.5,
        trace_logger=TraceLogger(),
        monotonic_clock=lambda: times[0],
    )
    return runtime_loop, event_queue, request_queue


@pytest.mark.asyncio
async def test_autonomous_planning_disabled_never_enqueues_request() -> None:
    runtime_loop, _, requests = _loop(enabled=False)

    assert await runtime_loop.run_once() is None
    assert requests.empty()


@pytest.mark.asyncio
async def test_startup_completion_gates_autonomous_planning() -> None:
    runtime_loop, events, requests = _loop(require_startup=True)

    assert await runtime_loop.run_once() is None
    assert requests.empty()
    await events.put(AgentEvent(event_type=AgentEventType.APP_STARTED))
    assert await runtime_loop.run_once() is not None
    assert runtime_loop.startup_completed is True
    assert await runtime_loop.run_once() is None
    assert requests.qsize() == 1


@pytest.mark.asyncio
async def test_poll_interval_prevents_duplicate_request_until_due() -> None:
    clock = [10.0]
    runtime_loop, _, requests = _loop(clock=clock)

    await runtime_loop.run_once()
    requests.get_nowait()
    clock[0] = 10.4
    await runtime_loop.run_once()
    assert requests.empty()
    clock[0] = 10.5
    await runtime_loop.run_once()
    assert requests.qsize() == 1


@pytest.mark.asyncio
async def test_busy_planner_prevents_new_request() -> None:
    runtime_loop, _, requests = _loop(busy=True)

    assert await runtime_loop.run_once() is None
    assert requests.empty()
