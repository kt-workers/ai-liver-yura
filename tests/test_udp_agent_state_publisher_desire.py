import json

from app.adapters.telemetry import (
    UdpAgentStatePublisher,
    UdpAgentStatePublisherConfig,
)
from app.domain.desires import DesireState, DesireType, DesireValue
from app.runtime.agent_state import AgentState


class RecordingSocket:
    def __init__(self) -> None:
        self.packets: list[tuple[bytes, tuple[str, int]]] = []

    def sendto(self, data: bytes, address: tuple[str, int]) -> int:
        self.packets.append((data, address))
        return len(data)


def test_publisher_includes_observational_desire_snapshot() -> None:
    socket = RecordingSocket()
    publisher = UdpAgentStatePublisher(
        UdpAgentStatePublisherConfig(host="127.0.0.1", port=9876),
        socket_factory=lambda: socket,
    )
    desire = DesireState().with_value(
        DesireType.RECOGNITION,
        DesireValue(
            level=0.7,
            baseline=0.3,
            sensitivity=0.8,
            satisfaction=0.1,
            frustration=0.2,
        ),
    )

    publisher.publish(AgentState().with_desire(desire))

    assert len(socket.packets) == 1
    packet, address = socket.packets[0]
    payload = json.loads(packet.decode("utf-8"))
    assert address == ("127.0.0.1", 9876)
    assert payload["schema_version"] == 1
    assert set(payload["desire"]) == set(desire.effective_values())
    assert payload["desire"]["recognition"] == {
        "level": 0.7,
        "baseline": 0.3,
        "sensitivity": 0.8,
        "satisfaction": 0.1,
        "frustration": 0.2,
        "effective_level": 0.8,
    }
    assert "emotion" in payload
    assert "drive" in payload
    assert "activity" in payload


def test_disabled_publisher_does_not_send_desire_snapshot() -> None:
    socket = RecordingSocket()
    publisher = UdpAgentStatePublisher(
        UdpAgentStatePublisherConfig(enabled=False),
        socket_factory=lambda: socket,
    )

    publisher.publish(AgentState())

    assert socket.packets == []
