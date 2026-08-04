import json

import pytest

from app.adapters.avatar import HttpAvatarOutput, HttpAvatarOutputConfig
from app.domain.avatar_performance import (
    AvatarExpressionIntent,
    AvatarGestureIntent,
    AvatarPerformancePlan,
    AvatarPerformanceSegment,
)
from app.ports.avatar_output import AvatarGazeIntent


@pytest.mark.asyncio
async def test_http_avatar_output_sends_expression_gesture_and_gaze() -> None:
    requests: list[tuple[str, dict[str, object], float]] = []

    def send_json(url: str, body: bytes, timeout_seconds: float) -> None:
        requests.append((url, json.loads(body.decode("utf-8")), timeout_seconds))

    output = HttpAvatarOutput(
        HttpAvatarOutputConfig(
            base_url="https://avatar.example.test/",
            timeout_seconds=1.5,
        ),
        send_json=send_json,
    )

    await output.set_expression("happy")
    await output.play_gesture("small_nod")
    await output.set_gaze(
        AvatarGazeIntent(
            target="viewer",
            behavior="maintain",
            intensity=0.8,
        )
    )

    assert [request[0] for request in requests] == [
        "https://avatar.example.test/api/avatar/actions",
        "https://avatar.example.test/api/avatar/actions",
        "https://avatar.example.test/api/avatar/actions",
    ]
    assert requests[0][1] == {
        "schema_version": 1,
        "type": "avatar.action",
        "action": "expression",
        "name": "happy",
        "intensity": 1.0,
    }
    assert requests[1][1]["action"] == "gesture"
    assert requests[1][1]["name"] == "small_nod"
    assert requests[2][1] == {
        "schema_version": 1,
        "type": "avatar.action",
        "action": "gaze",
        "target": "viewer",
        "behavior": "maintain",
        "intensity": 0.8,
    }
    assert all(request[2] == 1.5 for request in requests)


@pytest.mark.asyncio
async def test_http_avatar_output_sends_performance_plan() -> None:
    requests: list[tuple[str, dict[str, object], float]] = []

    def send_json(url: str, body: bytes, timeout_seconds: float) -> None:
        requests.append((url, json.loads(body.decode("utf-8")), timeout_seconds))

    output = HttpAvatarOutput(
        HttpAvatarOutputConfig(base_url="https://avatar.example.test"),
        send_json=send_json,
    )
    performance = AvatarPerformancePlan(
        performance_id="perf-001",
        source_activity_id="activity-001",
        output_unit_id="output-001",
        priority=100,
        segments=(
            AvatarPerformanceSegment(
                expression=AvatarExpressionIntent("curious", 0.7),
                gesture=AvatarGestureIntent("head_tilt", 0.4),
                gaze=AvatarGazeIntent("viewer", intensity=0.8),
                duration_ms=1800,
                fade_in_ms=200,
                fade_out_ms=300,
            ),
        ),
    )

    await output.submit_performance(performance)

    assert requests == [
        (
            "https://avatar.example.test/api/avatar/performances",
            {
                "schema_version": 1,
                "type": "avatar.performance.submit",
                "performance_id": "perf-001",
                "source_activity_id": "activity-001",
                "output_unit_id": "output-001",
                "priority": 100,
                "interrupt_policy": "replace_lower_priority",
                "return_behavior": "neutral",
                "segments": [
                    {
                        "expression": {
                            "name": "curious",
                            "intensity": 0.7,
                        },
                        "gesture": {
                            "name": "head_tilt",
                            "intensity": 0.4,
                        },
                        "gaze": {
                            "target": "viewer",
                            "behavior": "maintain",
                            "intensity": 0.8,
                        },
                        "duration_ms": 1800,
                        "fade_in_ms": 200,
                        "fade_out_ms": 300,
                    }
                ],
            },
            3.0,
        )
    ]


def test_http_avatar_output_config_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="base_url"):
        HttpAvatarOutputConfig(base_url="")
    with pytest.raises(ValueError, match="http"):
        HttpAvatarOutputConfig(base_url="avatar.example.test")
    with pytest.raises(ValueError, match="timeout_seconds"):
        HttpAvatarOutputConfig(
            base_url="https://avatar.example.test",
            timeout_seconds=0,
        )


def test_avatar_gaze_intent_validates_intensity() -> None:
    with pytest.raises(ValueError, match="intensity"):
        AvatarGazeIntent(target="viewer", intensity=1.1)
