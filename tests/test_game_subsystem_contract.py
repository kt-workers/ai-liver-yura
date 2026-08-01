from __future__ import annotations

import operator

import pytest

from app.integrations.games import (
    GAME_SUBSYSTEM_NOT_CONNECTED,
    GameCommandType,
    GameEventType,
    GameSubsystemCommand,
    GameSubsystemEvent,
    GameSubsystemGateway,
    GameSubsystemStatus,
    NullGameSubsystemGateway,
)


def _as_gateway(gateway: GameSubsystemGateway) -> GameSubsystemGateway:
    """Keep structural Protocol conformance visible to static type checking."""

    return gateway


def test_contract_enums_are_stable_and_complete() -> None:
    assert {status.value for status in GameSubsystemStatus} == {
        "disconnected",
        "unavailable",
        "ready",
        "busy",
        "degraded",
    }
    assert {command_type.value for command_type in GameCommandType} == {
        "start",
        "input",
        "pause",
        "resume",
        "stop",
        "reset",
    }
    assert {event_type.value for event_type in GameEventType} == {
        "status_changed",
        "session_started",
        "output_available",
        "session_ended",
        "error",
    }


def test_command_copies_payload_into_an_immutable_mapping() -> None:
    source: dict[str, object] = {"game": "example"}
    command = GameSubsystemCommand(
        command_id="command-1",
        command_type=GameCommandType.START,
        payload=source,
        correlation_id="correlation-1",
    )

    source["game"] = "changed"

    assert command.payload == {"game": "example"}
    with pytest.raises(TypeError):
        operator.setitem(command.payload, "game", "changed")


def test_event_copies_payload_into_an_immutable_mapping() -> None:
    source: dict[str, object] = {"output": "example"}
    event = GameSubsystemEvent(
        event_id="event-1",
        event_type=GameEventType.OUTPUT_AVAILABLE,
        payload=source,
        correlation_id="correlation-1",
    )

    source["output"] = "changed"

    assert event.payload == {"output": "example"}
    with pytest.raises(TypeError):
        operator.setitem(event.payload, "output", "changed")


@pytest.mark.asyncio
async def test_null_gateway_has_stable_disconnected_state() -> None:
    gateway = _as_gateway(NullGameSubsystemGateway())

    assert await gateway.get_status() is GameSubsystemStatus.DISCONNECTED
    assert await gateway.get_snapshot() == await gateway.get_snapshot()

    snapshot = await gateway.get_snapshot()
    assert snapshot.status is GameSubsystemStatus.DISCONNECTED
    assert snapshot.active_session_id is None
    assert snapshot.message == GAME_SUBSYSTEM_NOT_CONNECTED
    assert await gateway.poll_events() == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("command_type", list(GameCommandType))
async def test_null_gateway_rejects_every_command_stably(
    command_type: GameCommandType,
) -> None:
    gateway = _as_gateway(NullGameSubsystemGateway())
    command = GameSubsystemCommand(
        command_id=f"command-{command_type.value}",
        command_type=command_type,
        payload={"value": object()},
    )

    first = await gateway.send_command(command)
    second = await gateway.send_command(command)

    assert first == second
    assert first.accepted is False
    assert first.status is GameSubsystemStatus.DISCONNECTED
    assert first.reason == GAME_SUBSYSTEM_NOT_CONNECTED
