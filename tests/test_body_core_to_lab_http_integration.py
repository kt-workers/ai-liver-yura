from __future__ import annotations

import asyncio

import pytest

from app.adapters.avatar.body_pose_http_config import HttpBodyPoseOutputConfig
from app.adapters.avatar.http_body_pose_output import HttpBodyPoseFrameOutput
from tests.support.body_pose_frame_factory import make_body_pose_frame
from tests.support.body_pose_lab_http_harness import BodyPoseLabHttpHarness


async def wait_for_sent_count(
    output: HttpBodyPoseFrameOutput,
    expected: int,
) -> None:
    for _ in range(200):
        if output.snapshot().sent_count >= expected:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"BodyPoseFrame sent_count did not reach {expected}")


@pytest.mark.asyncio
async def test_core_http_output_reaches_real_body_pose_lab() -> None:
    with BodyPoseLabHttpHarness.start(local_simulation=False) as harness:
        output = HttpBodyPoseFrameOutput(
            HttpBodyPoseOutputConfig(
                base_url=harness.base_url,
                timeout_seconds=1.0,
                source_name="core-integration-test",
            )
        )
        try:
            first = make_body_pose_frame(
                1,
                head_yaw=0.28,
                right_arm_raise=0.42,
            )
            await output.publish_body_pose_frame(first)
            await wait_for_sent_count(output, 1)

            _, first_snapshot = harness.json_request("GET", "/api/snapshot")
            assert first_snapshot["frames"]["latest_source"] == "core-integration-test"
            assert first_snapshot["frames"]["latest_sequence"] == 1

            await output.publish_body_pose_frame(first)
            await wait_for_sent_count(output, 2)
            _, stale_snapshot = harness.json_request("GET", "/api/snapshot")
            assert stale_snapshot["frames"]["latest_sequence"] == 1
            assert stale_snapshot["frames"]["stale_count"] == 1

            second = make_body_pose_frame(
                2,
                head_yaw=-0.36,
                mouth_open=0.65,
            )
            await output.publish_body_pose_frame(second)
            await wait_for_sent_count(output, 3)
            _, latest_snapshot = harness.json_request("GET", "/api/snapshot")
            assert latest_snapshot["frames"]["latest_sequence"] == 2
            assert latest_snapshot["frames"]["received_count"] == 2
            assert output.snapshot().failed_count == 0
        finally:
            await output.close()
