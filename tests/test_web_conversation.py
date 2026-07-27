import asyncio
import json
from typing import Any
from urllib.request import Request

import pytest

from app.adapters.input.web_input_receiver import (
    WebInputReceiverConfig,
    _WebInputProtocol,
)
from app.adapters.web_conversation import (
    WebConversationClient,
    WebConversationClientConfig,
)
from app.domain.events import AgentEvent, AgentEventType, InputAuthority


@pytest.mark.asyncio
async def test_web_input_protocol_accepts_only_valid_user_text() -> None:
    events: list[AgentEvent] = []
    tasks: set[asyncio.Task[None]] = set()

    async def publish(event: AgentEvent) -> None:
        events.append(event)

    def finished(task: asyncio.Task[None]) -> None:
        tasks.discard(task)
        task.result()

    protocol = _WebInputProtocol(
        publish,
        WebInputReceiverConfig(),
        tasks.add,
        finished,
    )
    protocol.datagram_received(b"not-json", ("127.0.0.1", 1))
    protocol.datagram_received(
        json.dumps(
            {"schema_version": 1, "type": "user_text", "text": "  こんにちは  "},
            ensure_ascii=False,
        ).encode(),
        ("127.0.0.1", 1),
    )
    await asyncio.gather(*tuple(tasks))

    assert len(events) == 1
    assert events[0].payload == {"text": "こんにちは", "source": "web"}
    assert events[0].authority == InputAuthority.USER


@pytest.mark.asyncio
async def test_web_input_protocol_converts_visualizer_tap_to_interaction() -> None:
    events: list[AgentEvent] = []
    tasks: set[asyncio.Task[None]] = set()

    async def publish(event: AgentEvent) -> None:
        events.append(event)

    def finished(task: asyncio.Task[None]) -> None:
        tasks.discard(task)
        task.result()

    protocol = _WebInputProtocol(
        publish,
        WebInputReceiverConfig(),
        tasks.add,
        finished,
    )
    protocol.datagram_received(
        json.dumps(
            {
                "schema_version": 1,
                "type": "interaction_stimulus",
                "stimulus_kind": "tap",
                "position": {"x": 0.25, "y": 0.75},
            }
        ).encode(),
        ("127.0.0.1", 1),
    )
    protocol.datagram_received(
        json.dumps(
            {
                "schema_version": 1,
                "type": "interaction_stimulus",
                "stimulus_kind": "tap",
                "position": {"x": 0.5, "y": 0.5},
            }
        ).encode(),
        ("127.0.0.1", 1),
    )
    await asyncio.gather(*tuple(tasks))

    assert len(events) == 1
    assert events[0].event_type == AgentEventType.USER_INTERACTION
    assert events[0].payload["source"] == "inner_state_visualizer"
    assert events[0].payload["stimulus_description"] == ("ユーザーからそっと触れられた")
    assert events[0].payload["position"] == {"x": 0.25, "y": 0.75}
    assert events[0].payload["contact_region"] == "lower"
    assert events[0].payload["interaction_burst_count"] == 1
    assert events[0].payload["interval_since_previous_ms"] is None
    assert "emotion_appraisal" not in events[0].payload
    assert events[0].authority == InputAuthority.USER


@pytest.mark.asyncio
async def test_web_input_protocol_preserves_visualizer_gesture_kinds() -> None:
    events: list[AgentEvent] = []
    tasks: set[asyncio.Task[None]] = set()

    async def publish(event: AgentEvent) -> None:
        events.append(event)

    def finished(task: asyncio.Task[None]) -> None:
        tasks.discard(task)
        task.result()

    protocol = _WebInputProtocol(
        publish,
        WebInputReceiverConfig(),
        tasks.add,
        finished,
    )
    payloads = [
        {
            "schema_version": 1,
            "type": "interaction_stimulus",
            "stimulus_kind": "double_tap",
            "position": {"x": 0.4, "y": 0.6},
        },
        {
            "schema_version": 1,
            "type": "interaction_stimulus",
            "stimulus_kind": "long_press",
            "position": {"x": 0.5, "y": 0.5},
            "duration_ms": 800,
        },
        {
            "schema_version": 1,
            "type": "interaction_stimulus",
            "stimulus_kind": "drag",
            "start_position": {"x": 0.2, "y": 0.3},
            "position": {"x": 0.8, "y": 0.7},
            "duration_ms": 900,
        },
    ]
    for payload in payloads:
        protocol.datagram_received(json.dumps(payload).encode(), ("127.0.0.1", 1))
    await asyncio.gather(*tuple(tasks))

    assert [event.payload["stimulus_kind"] for event in events] == [
        "double_tap",
        "long_press",
        "drag",
    ]
    assert [event.payload["stimulus_description"] for event in events] == [
        "ユーザーから続けて二度触れられた",
        "ユーザーからしばらく触れ続けられた",
        "ユーザーから指でなぞられた",
    ]
    assert events[1].payload["duration_ms"] == 800
    assert events[2].payload["start_position"] == {"x": 0.2, "y": 0.3}
    assert [event.payload["interaction_burst_count"] for event in events] == [
        1,
        2,
        3,
    ]
    assert [event.payload["contact_region"] for event in events] == [
        "center",
        "center",
        "lower",
    ]


@pytest.mark.asyncio
async def test_web_input_protocol_preserves_continuous_drag_as_one_burst() -> None:
    events: list[AgentEvent] = []
    tasks: set[asyncio.Task[None]] = set()

    async def publish(event: AgentEvent) -> None:
        events.append(event)

    def finished(task: asyncio.Task[None]) -> None:
        tasks.discard(task)
        task.result()

    protocol = _WebInputProtocol(
        publish,
        WebInputReceiverConfig(drag_stream_min_interval_seconds=0),
        tasks.add,
        finished,
    )
    samples = [
        ("start", 0, (0.40, 0.50), (0.44, 0.49), 120),
        ("update", 1, (0.44, 0.49), (0.49, 0.47), 260),
        ("end", 2, (0.49, 0.47), (0.53, 0.46), 390),
    ]
    for phase, sequence, start, position, duration_ms in samples:
        protocol.datagram_received(
            json.dumps(
                {
                    "schema_version": 1,
                    "type": "interaction_stimulus",
                    "stimulus_kind": "drag",
                    "gesture_id": "drag-test",
                    "gesture_phase": phase,
                    "gesture_sequence": sequence,
                    "start_position": {"x": start[0], "y": start[1]},
                    "position": {"x": position[0], "y": position[1]},
                    "duration_ms": duration_ms,
                    "particle_zone": {
                        "center": {"x": 0.5, "y": 0.49},
                        "radius_x": 0.2,
                        "radius_y": 0.3,
                    },
                }
            ).encode(),
            ("127.0.0.1", 1),
        )
    await asyncio.gather(*tuple(tasks))

    assert len(events) == 3
    assert [event.payload["gesture_phase"] for event in events] == [
        "start",
        "update",
        "end",
    ]
    assert [event.payload["gesture_sequence"] for event in events] == [0, 1, 2]
    assert [event.payload["interaction_burst_count"] for event in events] == [
        1,
        1,
        1,
    ]
    assert all(event.payload["contact_motion"] == "trace" for event in events)
    assert all(event.payload["continuous_contact"] is True for event in events)
    assert events[1].payload["stimulus_description"] == ("ユーザーのドラッグが粒子の領域に触れた")
    assert events[0].payload["contact_phase"] == "start"
    assert events[-1].payload["contact_phase"] == "end"
    assert events[1].payload["motion"]["center_distance_ratio"] < 0.2
    assert events[1].payload["start_position"] == {"x": 0.44, "y": 0.49}
    assert events[1].payload["position"] == {"x": 0.49, "y": 0.47}
    assert events[1].payload["duration_ms"] == 260


@pytest.mark.asyncio
async def test_web_input_protocol_rejects_out_of_order_drag_sample() -> None:
    events: list[AgentEvent] = []
    tasks: set[asyncio.Task[None]] = set()

    async def publish(event: AgentEvent) -> None:
        events.append(event)

    def finished(task: asyncio.Task[None]) -> None:
        tasks.discard(task)
        task.result()

    protocol = _WebInputProtocol(
        publish,
        WebInputReceiverConfig(drag_stream_min_interval_seconds=0),
        tasks.add,
        finished,
    )
    for sequence in (0, 0):
        protocol.datagram_received(
            json.dumps(
                {
                    "schema_version": 1,
                    "type": "interaction_stimulus",
                    "stimulus_kind": "drag",
                    "gesture_id": "drag-test",
                    "gesture_phase": "start" if not events else "update",
                    "gesture_sequence": sequence,
                    "start_position": {"x": 0.4, "y": 0.5},
                    "position": {"x": 0.44, "y": 0.49},
                    "duration_ms": 120,
                    "particle_zone": {
                        "center": {"x": 0.5, "y": 0.49},
                        "radius_x": 0.2,
                        "radius_y": 0.3,
                    },
                }
            ).encode(),
            ("127.0.0.1", 1),
        )
        await asyncio.gather(*tuple(tasks))

    assert len(events) == 1


@pytest.mark.asyncio
async def test_web_input_protocol_only_emits_contact_inside_particle_zone() -> None:
    events: list[AgentEvent] = []
    tasks: set[asyncio.Task[None]] = set()

    async def publish(event: AgentEvent) -> None:
        events.append(event)

    def finished(task: asyncio.Task[None]) -> None:
        tasks.discard(task)
        task.result()

    protocol = _WebInputProtocol(
        publish,
        WebInputReceiverConfig(drag_stream_min_interval_seconds=0),
        tasks.add,
        finished,
    )
    for phase, sequence, x in [
        ("start", 0, 0.1),
        ("update", 1, 0.3),
        ("update", 2, 0.42),
        ("end", 3, 0.1),
    ]:
        protocol.datagram_received(
            json.dumps(
                {
                    "schema_version": 1,
                    "type": "interaction_stimulus",
                    "stimulus_kind": "drag",
                    "gesture_id": "drag-entry",
                    "gesture_phase": phase,
                    "gesture_sequence": sequence,
                    "start_position": {"x": x - 0.02, "y": 0.49},
                    "position": {"x": x, "y": 0.49},
                    "duration_ms": sequence * 150,
                    "particle_zone": {
                        "center": {"x": 0.5, "y": 0.49},
                        "radius_x": 0.1,
                        "radius_y": 0.2,
                    },
                }
            ).encode(),
            ("127.0.0.1", 1),
        )
    await asyncio.gather(*tuple(tasks))

    assert len(events) == 1
    assert events[0].payload["position"] == {"x": 0.42, "y": 0.49}
    assert events[0].payload["gesture_phase"] == "update"
    assert events[0].payload["contact_phase"] == "start"
    assert events[0].payload["interaction_burst_count"] == 1


@pytest.mark.asyncio
async def test_web_input_protocol_recognizes_back_and_forth_stroking() -> None:
    events: list[AgentEvent] = []
    tasks: set[asyncio.Task[None]] = set()

    async def publish(event: AgentEvent) -> None:
        events.append(event)

    def finished(task: asyncio.Task[None]) -> None:
        tasks.discard(task)
        task.result()

    protocol = _WebInputProtocol(
        publish,
        WebInputReceiverConfig(drag_stream_min_interval_seconds=0),
        tasks.add,
        finished,
    )
    positions = [0.40, 0.50, 0.42, 0.52]
    for sequence, x in enumerate(positions):
        phase = "start" if sequence == 0 else "end" if sequence == len(positions) - 1 else "update"
        protocol.datagram_received(
            json.dumps(
                {
                    "schema_version": 1,
                    "type": "interaction_stimulus",
                    "stimulus_kind": "drag",
                    "gesture_id": "drag-stroke",
                    "gesture_phase": phase,
                    "gesture_sequence": sequence,
                    "start_position": {
                        "x": positions[max(0, sequence - 1)],
                        "y": 0.49,
                    },
                    "position": {"x": x, "y": 0.49},
                    "duration_ms": sequence * 180,
                    "particle_zone": {
                        "center": {"x": 0.5, "y": 0.49},
                        "radius_x": 0.2,
                        "radius_y": 0.3,
                    },
                }
            ).encode(),
            ("127.0.0.1", 1),
        )
    await asyncio.gather(*tuple(tasks))

    assert len(events) == 4
    final = events[-1].payload
    assert final["contact_motion"] == "stroke"
    assert final["motion"]["back_and_forth"] is True
    assert final["motion"]["reversal_count"] == 2
    assert final["motion"]["path_distance_ratio"] > 1.0
    assert final["motion"]["center_distance_ratio"] == pytest.approx(0.1)
    touch_features = final["touch_features"]
    assert touch_features["location"] == {
        "vertical": "middle",
        "radial": "inner",
        "relative_x": 0.1,
        "relative_y": 0.0,
        "center_distance_ratio": 0.1,
    }
    assert touch_features["movement"]["speed_band"] in {"brisk", "rapid"}
    assert touch_features["movement"]["trajectory_shape"] in {
        "oscillating",
        "erratic",
    }
    assert touch_features["movement"]["oscillation"] > 0.5
    assert "reaction" not in touch_features
    assert "emotion" not in touch_features


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def read(self) -> bytes:
        return self._body


@pytest.mark.asyncio
async def test_web_conversation_client_publishes_text_and_waits_for_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[Request] = []

    def fake_urlopen(request: Request, timeout: float) -> _Response:
        del timeout
        requests.append(request)
        return _Response(b'{"status":"completed"}')

    monkeypatch.setattr(
        "app.adapters.web_conversation.client.urlopen",
        fake_urlopen,
    )
    client = WebConversationClient(WebConversationClientConfig(base_url="http://127.0.0.1:18770"))

    await client.publish_text(kind="speak", text="こんにちは", action_id="action-1")
    await client.play(b"RIFF-test-wav")

    assert [request.full_url for request in requests] == [
        "http://127.0.0.1:18770/api/output",
        "http://127.0.0.1:18770/api/audio",
    ]
    text_payload: dict[str, Any] = json.loads(bytes(requests[0].data or b""))
    assert text_payload["text"] == "こんにちは"
    assert requests[1].data == b"RIFF-test-wav"
