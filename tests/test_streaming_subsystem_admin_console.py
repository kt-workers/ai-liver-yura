import pytest

from subsystems.streaming.admin_api.service import StreamingAdminService
from subsystems.streaming.bootstrap import build_streaming_subsystem


@pytest.mark.asyncio
async def test_console_is_subsystem_owned_and_core_is_optional() -> None:
    console = await StreamingAdminService(build_streaming_subsystem()).console()
    assert console["subsystem_state"] == "idle"
    assert console["runtime_state"] == "idle"
    assert console["operator_action"]["action"] == "prepare"
    assert all(
        item["owner"] in {"streaming_subsystem", "core"} for item in console["responsibilities"]
    )


@pytest.mark.asyncio
async def test_console_keeps_browser_compatibility_fields() -> None:
    console = await StreamingAdminService(build_streaming_subsystem()).console()
    expected = {
        "generated_at",
        "current_state",
        "current_message",
        "subsystem_state",
        "services",
        "operator_action",
        "lifecycle_steps",
        "responsibilities",
        "timeline",
        "comments",
        "lifecycle",
        "log_settings",
    }
    assert expected <= set(console)
