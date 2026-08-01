import pytest

from app.domain.activities import ActivityStatus
from app.runtime.activity_manager import ActivityManager
from app.runtime.ongoing_activity_coordinator import OngoingActivityCoordinator
from app.runtime.plugin_ongoing_activity_synchronizer import (
    PluginActivitySynchronizationError,
    PluginOngoingActivitySynchronizer,
)
from app.shared.contracts.plugins.runtime import (
    PluginActivityState,
    PluginActivityStatus,
)
from app.utils.trace import TraceLogger

pytestmark = pytest.mark.unit


class SessionPlugin:
    plugin_id = "sample"

    def __init__(self, session_id: str = "session-1") -> None:
        self.session_id = session_id
        self.ongoing_activity_id: str | None = None
        self.rollback_reasons: list[str] = []

    def snapshot(self) -> dict[str, object]:
        return {"session_id": self.session_id}

    def link_ongoing_activity(self, ongoing_activity_id: str) -> None:
        self.ongoing_activity_id = ongoing_activity_id

    def rollback_active_session(self, reason: str) -> None:
        self.rollback_reasons.append(reason)


def _synchronizer() -> tuple[PluginOngoingActivitySynchronizer, ActivityManager]:
    manager = ActivityManager()
    return (
        PluginOngoingActivitySynchronizer(
            ongoing_activity_coordinator=OngoingActivityCoordinator(manager),
            trace_logger=TraceLogger(),
        ),
        manager,
    )


def _state(status: PluginActivityStatus) -> PluginActivityState:
    return PluginActivityState(
        session_id="session-1",
        status=status,
        expected_input="次の単語",
        end_condition="ゲーム終了",
    )


def _synchronize(
    synchronizer: PluginOngoingActivitySynchronizer,
    plugin: SessionPlugin,
    *,
    status: PluginActivityStatus,
    operation: str,
    turn_started: bool,
) -> None:
    synchronizer.synchronize(
        plugin=plugin,
        activity_state=_state(status),
        request_context={"plugin_id": "sample", "plugin_state_version": 1},
        activity_kind="plugin_task",
        activity_type="echo_activity",
        response_text="りんご",
        capability="sample.echo",
        operation=operation,
        constraints={"theme": "通常"},
        goal="エコー活動を続ける",
        input_text="ごりら",
        source_event_id=f"event-{operation}",
        turn_started=turn_started,
    )


def test_start_links_plugin_session_and_waiting_ongoing_activity() -> None:
    synchronizer, manager = _synchronizer()
    plugin = SessionPlugin()

    _synchronize(
        synchronizer,
        plugin,
        status=PluginActivityStatus.WAITING_INPUT,
        operation="start",
        turn_started=False,
    )

    ongoing = manager.ongoing_activity
    assert ongoing is not None
    assert ongoing.status == ActivityStatus.WAITING
    assert ongoing.context["plugin_session_id"] == "session-1"
    assert plugin.ongoing_activity_id == ongoing.ongoing_activity_id
    assert ongoing.turns[-1].execution_result is not None


def test_continue_begins_turn_before_recording_execution() -> None:
    synchronizer, manager = _synchronizer()
    plugin = SessionPlugin()
    _synchronize(
        synchronizer,
        plugin,
        status=PluginActivityStatus.WAITING_INPUT,
        operation="start",
        turn_started=False,
    )

    synchronizer.begin_turn(
        plugin=plugin,
        operation="continue",
        input_text="ごりら",
        source_event_id="event-continue",
        constraints={},
    )
    _synchronize(
        synchronizer,
        plugin,
        status=PluginActivityStatus.WAITING_INPUT,
        operation="continue",
        turn_started=True,
    )

    ongoing = manager.ongoing_activity
    assert ongoing is not None
    assert len(ongoing.turns) == 2
    assert ongoing.turns[-1].operation == "continue"
    assert ongoing.turns[-1].execution_result is not None


@pytest.mark.parametrize(
    ("status", "operation", "expected_status"),
    [
        (PluginActivityStatus.COMPLETED, "stop", ActivityStatus.COMPLETED),
        (PluginActivityStatus.CANCELED, "stop", ActivityStatus.CANCELED),
        (PluginActivityStatus.SUSPENDED, "continue", ActivityStatus.SUSPENDED),
    ],
)
def test_terminal_and_suspended_plugin_states_map_to_core_state(
    status: PluginActivityStatus,
    operation: str,
    expected_status: ActivityStatus,
) -> None:
    synchronizer, manager = _synchronizer()
    plugin = SessionPlugin()
    _synchronize(
        synchronizer,
        plugin,
        status=PluginActivityStatus.WAITING_INPUT,
        operation="start",
        turn_started=False,
    )
    synchronizer.begin_turn(
        plugin=plugin,
        operation=operation,
        input_text="終了",
        source_event_id=f"event-{operation}",
        constraints={},
    )

    _synchronize(
        synchronizer,
        plugin,
        status=status,
        operation=operation,
        turn_started=True,
    )

    if status == PluginActivityStatus.SUSPENDED:
        assert manager.ongoing_activity is not None
        assert manager.ongoing_activity.status == expected_status
    else:
        assert manager.ongoing_activity is None
        assert manager.ongoing_activity_history[-1].status == expected_status


def test_context_mismatch_rolls_back_plugin_and_core() -> None:
    synchronizer, manager = _synchronizer()
    plugin = SessionPlugin()
    _synchronize(
        synchronizer,
        plugin,
        status=PluginActivityStatus.WAITING_INPUT,
        operation="start",
        turn_started=False,
    )
    plugin.session_id = "different-session"

    with pytest.raises(
        PluginActivitySynchronizationError,
        match="ongoing_activity_context_mismatch",
    ):
        synchronizer.begin_turn(
            plugin=plugin,
            operation="continue",
            input_text="みかん",
            source_event_id="event-mismatch",
            constraints={},
        )

    assert manager.ongoing_activity is None
    assert manager.ongoing_activity_history[-1].status == ActivityStatus.CANCELED
    assert plugin.rollback_reasons == ["ongoing_activity_context_mismatch"]
