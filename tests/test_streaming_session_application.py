import pytest

from subsystems.streaming.bootstrap import build_streaming_subsystem
from subsystems.streaming.ports.content_execution import (
    UnavailableStreamContentExecutor,
)


def test_composition_root_owns_session_application_components() -> None:
    api = build_streaming_subsystem()
    assert api.sessions.prepare.list_run_of_shows()[0].run_of_show_id == "default"
    assert api.sessions.sessions.find_active_or_preparing() is None


@pytest.mark.asyncio
async def test_unconnected_content_execution_is_explicitly_unavailable() -> None:
    result = await UnavailableStreamContentExecutor()({}, "trace")
    assert result.final_status == "unavailable"
    assert result.failure_stage == "content_execution.not_connected"
