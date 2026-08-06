from __future__ import annotations

import asyncio
import json

import pytest

from app.adapters.avatar.body_pose_frame_json_encoder import BodyPoseFrameJsonEncoder
from app.adapters.avatar.body_pose_http_config import HttpBodyPoseOutputConfig
from app.adapters.avatar.body_pose_http_sender import BodyPoseHttpSender
from app.adapters.avatar.http_body_pose_output import HttpBodyPoseFrameOutput
from app.adapters.avatar.latest_body_pose_frame_buffer import LatestBodyPoseFrameBuffer
from app.domain.body_auxiliary_projection import (
    BodyTrackingPose,
    BodyTrackingVelocity,
)
from app.domain.body_motion_state import BodyInnerMotionState
from app.domain.body_pose_frame import BodyPoseFrame

pytestmark = pytest.mark.unit


def _frame(sequence: int) -> BodyPoseFrame:
    return BodyPoseFrame(
        sequence=sequence,
        timestamp_ms=sequence * 100,
        pose=BodyTrackingPose(head_yaw=sequence * 0.01),
        velocity=BodyTrackingVelocity(),
        inner_state=BodyInnerMotionState(),
    )


def test_http_body_pose_config_normalizes_endpoint() -> None:
    config = HttpBodyPoseOutputConfig(
        base_url=" http://127.0.0.1:8010/ ",
        endpoint_path="/api/body-pose-frame",
        timeout_seconds=0.5,
    )

    assert config.base_url == "http://127.0.0.1:8010"
    assert config.endpoint_url == "http://127.0.0.1:8010/api/body-pose-frame"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"base_url": "127.0.0.1:8010"},
        {"base_url": "http://127.0.0.1:8010?x=1"},
        {"base_url": "http://127.0.0.1:8010", "endpoint_path": "api/frame"},
        {"base_url": "http://127.0.0.1:8010", "timeout_seconds": 31.0},
    ],
)
def test_http_body_pose_config_rejects_invalid_values(kwargs: dict[str, object]) -> None:
    with pytest.raises((TypeError, ValueError)):
        HttpBodyPoseOutputConfig(**kwargs)  # type: ignore[arg-type]


def test_latest_frame_buffer_replaces_old_pending_frame() -> None:
    buffer = LatestBodyPoseFrameBuffer()

    assert buffer.offer(_frame(1)) is False
    assert buffer.offer(_frame(2)) is True

    assert buffer.pending_count == 1
    assert buffer.dropped_count == 1


@pytest.mark.asyncio
async def test_latest_frame_buffer_receives_latest_frame() -> None:
    buffer = LatestBodyPoseFrameBuffer()
    buffer.offer(_frame(1))
    buffer.offer(_frame(2))

    received = await buffer.receive()
    buffer.task_done()

    assert received.sequence == 2


def test_body_pose_json_encoder_keeps_schema_and_transport_metadata() -> None:
    body = BodyPoseFrameJsonEncoder().encode(
        _frame(3),
        source_name="test-source",
    )
    payload = json.loads(body.decode("utf-8"))

    assert payload["type"] == "body.pose.frame"
    assert payload["source"] == "test-source"
    assert payload["schema_version"] == 2
    assert payload["sequence"] == 3


@pytest.mark.asyncio
async def test_http_sender_posts_one_encoded_frame() -> None:
    calls: list[tuple[str, bytes, float]] = []
    config = HttpBodyPoseOutputConfig(base_url="http://example.test", timeout_seconds=0.4)
    sender = BodyPoseHttpSender(
        config,
        post_json=lambda url, body, timeout: calls.append((url, body, timeout)),
    )

    await sender.send(_frame(4))

    assert len(calls) == 1
    url, body, timeout = calls[0]
    assert url == "http://example.test/api/body-pose-frame"
    assert json.loads(body)["sequence"] == 4
    assert timeout == 0.4


class SlowSender:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.sent: list[int] = []

    async def send(self, frame: BodyPoseFrame) -> None:
        self.started.set()
        if not self.sent:
            await self.release.wait()
        self.sent.append(frame.sequence)


@pytest.mark.asyncio
async def test_http_output_drops_intermediate_frames_without_blocking_publish() -> None:
    sender = SlowSender()
    output = HttpBodyPoseFrameOutput(
        HttpBodyPoseOutputConfig(base_url="http://example.test"),
        sender=sender,  # type: ignore[arg-type]
    )

    await output.publish_body_pose_frame(_frame(1))
    await sender.started.wait()
    await output.publish_body_pose_frame(_frame(2))
    await output.publish_body_pose_frame(_frame(3))
    sender.release.set()

    for _ in range(100):
        if output.snapshot().sent_count >= 2:
            break
        await asyncio.sleep(0.001)

    snapshot = output.snapshot()
    await output.close()

    assert sender.sent == [1, 3]
    assert snapshot.sent_count == 2
    assert snapshot.dropped_count == 1
    assert snapshot.failed_count == 0


class FailingSender:
    async def send(self, frame: BodyPoseFrame) -> None:
        del frame
        raise RuntimeError("network down")


@pytest.mark.asyncio
async def test_http_output_records_error_and_continues() -> None:
    output = HttpBodyPoseFrameOutput(
        HttpBodyPoseOutputConfig(base_url="http://example.test"),
        sender=FailingSender(),  # type: ignore[arg-type]
    )

    await output.publish_body_pose_frame(_frame(1))
    for _ in range(100):
        if output.snapshot().failed_count:
            break
        await asyncio.sleep(0.001)

    snapshot = output.snapshot()
    await output.close()

    assert snapshot.failed_count == 1
    assert snapshot.sent_count == 0
    assert snapshot.last_error == "RuntimeError: network down"


@pytest.mark.asyncio
async def test_http_output_ignores_publish_after_close() -> None:
    output = HttpBodyPoseFrameOutput(
        HttpBodyPoseOutputConfig(base_url="http://example.test"),
        sender=SlowSender(),  # type: ignore[arg-type]
    )
    await output.close()

    await output.publish_body_pose_frame(_frame(1))

    assert output.snapshot().pending_count == 0
    assert output.snapshot().running is False
