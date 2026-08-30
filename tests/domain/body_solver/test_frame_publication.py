from datetime import datetime, timezone

import pytest

from app.domain.body import BodyPose, BodyVelocity, JointTransform, JointVelocity, Quaternion, Vector3
from app.domain.body_solver import (
    BodyFramePublicationError,
    BodyFramePublicationFailureCode,
    BodyPoseFrame,
    LatestBodyFrameBuffer,
)


def _transform() -> JointTransform:
    return JointTransform(Vector3(0, 0, 0), Quaternion(0, 0, 0, 1))


def _velocity() -> JointVelocity:
    return JointVelocity(Vector3(0, 0, 0), Vector3(0, 0, 0))


def _frame(revision: int, *, model_id: str = "yura.canonical.v1") -> BodyPoseFrame:
    return BodyPoseFrame(
        frame_id=f"frame-{revision}",
        body_model_id=model_id,
        body_state_revision=revision,
        observed_at=datetime(2026, 8, 30, 14, revision, tzinfo=timezone.utc),
        pose=BodyPose(_transform(), ()),
        velocity=BodyVelocity(_velocity(), ()),
        active_plan_id=None,
        active_trajectory_id=None,
        channel_values=(),
        applied_overlay_refs=(),
        degraded_overlay_refs=(),
        trace_id=f"trace-{revision}",
    )


def test_latest_body_frame_buffer_coalesces_slow_consumer_to_latest_frame() -> None:
    buffer = LatestBodyFrameBuffer("yura.canonical.v1")

    buffer.publish(_frame(1))
    buffer.publish(_frame(2))
    buffer.publish(_frame(3))

    result = buffer.take_latest()
    assert result.frame == _frame(3)
    assert result.coalesced_frames == 2
    assert buffer.peek_latest() is None
    assert buffer.last_published_revision == 3


def test_take_latest_resets_coalesced_count_without_rolling_back_revision() -> None:
    buffer = LatestBodyFrameBuffer("yura.canonical.v1")
    buffer.publish(_frame(1))

    first = buffer.take_latest()
    second = buffer.take_latest()

    assert first.frame == _frame(1)
    assert first.coalesced_frames == 0
    assert second.frame is None
    assert second.coalesced_frames == 0
    assert buffer.last_published_revision == 1


def test_latest_body_frame_buffer_rejects_stale_or_duplicate_revision() -> None:
    buffer = LatestBodyFrameBuffer("yura.canonical.v1")
    buffer.publish(_frame(2))

    with pytest.raises(BodyFramePublicationError) as duplicate:
        buffer.publish(_frame(2))
    assert duplicate.value.code is BodyFramePublicationFailureCode.STALE_REVISION

    with pytest.raises(BodyFramePublicationError) as stale:
        buffer.publish(_frame(1))
    assert stale.value.code is BodyFramePublicationFailureCode.STALE_REVISION
    assert buffer.peek_latest() == _frame(2)


def test_latest_body_frame_buffer_rejects_other_canonical_model() -> None:
    buffer = LatestBodyFrameBuffer("yura.canonical.v1")

    with pytest.raises(BodyFramePublicationError) as error:
        buffer.publish(_frame(1, model_id="other.model"))

    assert error.value.code is BodyFramePublicationFailureCode.MODEL_MISMATCH
    assert buffer.peek_latest() is None
