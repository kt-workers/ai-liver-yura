import json

import pytest

from app.adapters.avatar import HttpAvatarOutput, HttpAvatarOutputConfig
from app.domain.avatar_performance import (
    AvatarBlendMode,
    AvatarExpressionIntent,
    AvatarGestureIntent,
    AvatarMotionIntent,
    AvatarPerformancePlan,
    AvatarPerformanceSegment,
    AvatarPerformanceTrack,
    AvatarTrackChannel,
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
    await output.set_gaze(AvatarGazeIntent("viewer", intensity=0.8))

    assert [request[0] for request in requests] == [
        "https://avatar.example.test/api/avatar/actions",
        "https://avatar.example.test/api/avatar/actions",
        "https://avatar.example.test/api/avatar/actions",
    ]
    assert requests[0][1]["action"] == "expression"
    assert requests[1][1]["action"] == "gesture"
    assert requests[2][1]["action"] == "gaze"
    assert all(request[2] == 1.5 for request in requests)


@pytest.mark.asyncio
async def test_http_avatar_output_sends_overlapping_track_plan() -> None:
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
        tracks=(
            AvatarPerformanceTrack(
                track_id="attention",
                channel=AvatarTrackChannel.ATTENTION,
                start_offset_ms=0,
                duration_ms=3000,
                hold=True,
                attention=AvatarGazeIntent("cursor", head_follow=0.6),
            ),
            AvatarPerformanceTrack(
                track_id="head-shake",
                channel=AvatarTrackChannel.HEAD,
                start_offset_ms=200,
                duration_ms=1200,
                blend_mode=AvatarBlendMode.ADDITIVE,
                motion=AvatarMotionIntent(
                    "head_shake",
                    intensity=0.8,
                    repetitions=3,
                ),
            ),
        ),
    )

    await output.submit_performance(performance)

    assert len(requests) == 1
    url, payload, timeout = requests[0]
    assert url == "https://avatar.example.test/api/avatar/performances"
    assert timeout == 3.0
    assert payload["schema_version"] == 2
    assert payload["return_behavior"] == "hold"
    assert payload["duration_ms"] == 3000
    assert len(payload["tracks"]) == 2
    attention = payload["tracks"][0]
    motion = payload["tracks"][1]
    assert attention["channel"] == "attention"
    assert attention["hold"] is True
    assert attention["intent"]["target"] == "cursor"
    assert attention["intent"]["head_follow"] == 0.6
    assert motion["channel"] == "head"
    assert motion["blend_mode"] == "additive"
    assert motion["intent"]["name"] == "head_shake"
    assert motion["intent"]["repetitions"] == 3
    assert payload["segments"][0]["gesture"]["name"] == "head_tilt"


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
