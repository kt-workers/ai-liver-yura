from dataclasses import dataclass

import pytest

from app.domain.actions import ActionPlanGroup
from app.domain.activities import Activity
from app.domain.behavior import ActivityOperation, ActivityPlan, BehaviorDecision
from app.domain.character_response import (
    ActivityExecutionResult,
    ActivityExecutionStatus,
)
from app.domain.events import AgentEvent, AgentEventType
from app.runtime.activity_manager import ActivityManager
from app.runtime.plugin_activity_coordinator import PluginActivityCoordinator
from app.shared.contracts.plugins.runtime import (
    PluginActivityRequest,
    PluginActivityState,
    PluginActivityStatus,
    PluginCapability,
    PluginCommand,
    PluginExecutionResult,
    PluginIntentResult,
)
from app.utils.trace import TraceLogger

pytestmark = pytest.mark.unit


@dataclass
class FakeExplicitExecutor:
    executed: list[Activity]

    async def execute(self, activity: Activity) -> ActionPlanGroup:
        self.executed.append(activity)
        return ActionPlanGroup()


class FakeSynchronizer:
    def __init__(self, manager: ActivityManager, *, fail: bool = False) -> None:
        self._manager = manager
        self._fail = fail

    def begin_turn(self, **_: object) -> None:
        return None

    def synchronize(
        self,
        **_: object,
    ) -> tuple[ActivityExecutionResult, object]:
        if self._fail:
            raise RuntimeError("sync failed")
        ongoing = self._manager.start_ongoing_activity(
            activity_type="echo_activity",
            goal="遊ぶ",
            expected_input="次の単語",
            end_condition="終了",
            context={"plugin_id": "sample", "plugin_session_id": "session-1"},
        )
        return (
            ActivityExecutionResult(
                activity_type="echo_activity",
                operation="start",
                status=ActivityExecutionStatus.WAITING_INPUT,
            ),
            ongoing,
        )

    def record_failed_turn(self, **_: object) -> None:
        return None


class FakePlugin:
    plugin_id = "sample"

    def __init__(
        self,
        intent: PluginIntentResult,
        execution: PluginExecutionResult,
    ) -> None:
        self._intent = intent
        self._execution = execution
        self.command_calls = 0

    async def interpret_activity_plan(
        self,
        activity_plan: ActivityPlan,
        text: str,
    ) -> PluginIntentResult:
        del activity_plan, text
        return self._intent

    async def interpret_user_text(self, text: str) -> PluginIntentResult:
        del text
        return self._intent

    async def execute_command(
        self,
        intent: PluginIntentResult,
    ) -> PluginExecutionResult:
        del intent
        self.command_calls += 1
        return self._execution


class FakePluginManager:
    def __init__(
        self,
        plugin: FakePlugin,
        *,
        activity_available: bool = True,
        handler_available: bool = True,
    ) -> None:
        self._plugin = plugin
        self._activity_available = activity_available
        self._handler_available = handler_available

    def get_plugins_by_capability(self, capability: str) -> list[FakePlugin]:
        assert capability == PluginCapability.USER_INTENT_INTERPRETER.value
        return [self._plugin]

    def list_capabilities(self) -> frozenset[str]:
        return frozenset(
            {
                "sample.echo",
                PluginCapability.COMMAND_HANDLER.value,
                PluginCapability.USER_INTENT_INTERPRETER.value,
            }
        )

    def is_capability_available(self, capability: str, plugin_id: str) -> bool:
        assert plugin_id == "sample"
        if capability == PluginCapability.COMMAND_HANDLER.value:
            return self._handler_available
        return self._activity_available

    def set_capability_availability(
        self,
        plugin_id: str,
        capability: str,
        *,
        available: bool,
    ) -> None:
        del plugin_id, capability, available


def _plan() -> ActivityPlan:
    return ActivityPlan(
        decision=BehaviorDecision.START_ACTIVITY,
        activity_type="echo_activity",
        goal="エコー活動を開始する",
        required_capability="sample.echo",
        provider_plugin_id="sample",
        operation=ActivityOperation.START,
    )


def _intent(*, handled: bool = True) -> PluginIntentResult:
    return PluginIntentResult(
        plugin_id="sample",
        handled=handled,
        confidence=0.9,
        command=PluginCommand(command_type="echo_activity", operation="start"),
        conversation_context={"execution_requested": True},
    )


def _execution(
    *,
    handled: bool,
    with_request: bool = False,
    reason: str = "",
) -> PluginExecutionResult:
    request = (
        PluginActivityRequest(
            plugin_id="sample",
            activity_kind="game_with_user",
            priority=10,
            context={"plugin_id": "sample"},
            response_text="エコー活動を始めよう",
            state=PluginActivityState(
                session_id="session-1",
                status=PluginActivityStatus.WAITING_INPUT,
                expected_input="次の単語",
                end_condition="終了",
            ),
        )
        if with_request
        else None
    )
    return PluginExecutionResult(
        plugin_id="sample",
        handled=handled,
        activity_request=request,
        conversation_context={"execution_requested": True},
        reason=reason,
    )


def _coordinator(
    plugin_manager: object | None,
    *,
    synchronizer_fails: bool = False,
) -> tuple[PluginActivityCoordinator, FakeExplicitExecutor]:
    activity_manager = ActivityManager()
    executor = FakeExplicitExecutor([])
    coordinator = PluginActivityCoordinator(
        plugin_manager=plugin_manager,  # type: ignore[arg-type]
        activity_plan_validator=None,
        activity_manager=activity_manager,
        explicit_activity_executor=executor,  # type: ignore[arg-type]
        ongoing_synchronizer=FakeSynchronizer(
            activity_manager,
            fail=synchronizer_fails,
        ),  # type: ignore[arg-type]
        conversation_fallback=lambda event: event,
        execution_fallback=lambda event, contexts, reason, confidence: (
            AgentEvent(
                event_type=event.event_type,
                payload={
                    **event.payload,
                    "plugin_contexts": contexts,
                    "execution_match_reason": reason,
                    "execution_match_confidence": confidence,
                },
                trace_context=event.trace_context,
            )
        ),
        ongoing_transition_payload=lambda *_args, **_kwargs: {},
        trace_logger=TraceLogger(),
    )
    return coordinator, executor


def _event() -> AgentEvent:
    return AgentEvent(
        event_type=AgentEventType.USER_TEXT,
        payload={"text": "エコー活動しよう"},
    )


@pytest.mark.asyncio
async def test_plugin_not_configured_uses_compatibility_fallback() -> None:
    coordinator, _ = _coordinator(None)
    event = _event()

    assert await coordinator.route(event, activity_plan=_plan()) is event


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("activity_available", "handler_available", "reason"),
    [
        (False, True, "activity_capability_revoked_before_execution"),
        (True, False, "selected_capability_unavailable"),
    ],
)
async def test_capability_is_revalidated_immediately_before_execution(
    activity_available: bool,
    handler_available: bool,
    reason: str,
) -> None:
    plugin = FakePlugin(_intent(), _execution(handled=False))
    manager = FakePluginManager(
        plugin,
        activity_available=activity_available,
        handler_available=handler_available,
    )
    coordinator, executor = _coordinator(manager)

    routed = await coordinator.route(
        _event(),
        required_capability="sample.echo",
        activity_plan=_plan(),
    )

    assert routed is not None
    assert routed.payload["execution_match_reason"] == reason
    assert plugin.command_calls == 0
    assert executor.executed == []


@pytest.mark.asyncio
async def test_success_registers_and_executes_plugin_activity() -> None:
    plugin = FakePlugin(_intent(), _execution(handled=True, with_request=True))
    coordinator, executor = _coordinator(FakePluginManager(plugin))

    routed = await coordinator.route(
        _event(),
        required_capability="sample.echo",
        activity_plan=_plan(),
    )

    assert routed is None
    assert plugin.command_calls == 1
    assert len(executor.executed) == 1
    assert executor.executed[0].context["plugin_id"] == "sample"


@pytest.mark.asyncio
async def test_failed_execution_returns_reasoned_fallback() -> None:
    plugin = FakePlugin(
        _intent(),
        _execution(handled=False, reason="command_failed"),
    )
    coordinator, executor = _coordinator(FakePluginManager(plugin))

    routed = await coordinator.route(
        _event(),
        required_capability="sample.echo",
        activity_plan=_plan(),
    )

    assert routed is not None
    assert routed.payload["execution_match_reason"] == "command_failed"
    assert executor.executed == []


@pytest.mark.asyncio
async def test_unhandled_intent_uses_conversation_fallback() -> None:
    plugin = FakePlugin(_intent(handled=False), _execution(handled=False))
    coordinator, _ = _coordinator(FakePluginManager(plugin))
    event = _event()

    routed = await coordinator.route(event, activity_plan=_plan())

    assert routed is event
    assert plugin.command_calls == 0


@pytest.mark.asyncio
async def test_ongoing_sync_failure_returns_existing_fallback_reason() -> None:
    plugin = FakePlugin(_intent(), _execution(handled=True, with_request=True))
    coordinator, executor = _coordinator(
        FakePluginManager(plugin),
        synchronizer_fails=True,
    )

    routed = await coordinator.route(
        _event(),
        required_capability="sample.echo",
        activity_plan=_plan(),
    )

    assert routed is not None
    assert routed.payload["execution_match_reason"] == "ongoing_activity_sync_failed"
    assert executor.executed == []
