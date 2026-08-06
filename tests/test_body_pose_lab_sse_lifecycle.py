from __future__ import annotations

from time import sleep

from tests.support.body_pose_frame_factory import make_body_pose_frame
from tests.support.body_pose_lab_http_harness import BodyPoseLabHttpHarness


def test_sse_stream_delivers_first_body_pose_frame_event_over_http() -> None:
    with BodyPoseLabHttpHarness.start(local_simulation=False) as harness:
        frame = make_body_pose_frame(
            7,
            head_yaw=0.31,
            right_arm_raise=0.58,
        )
        assert harness.components.frame_hub.publish(
            frame,
            source="sse-test",
            received_at_ms=700,
        )

        event_name, payload = harness.first_sse_event()

        assert event_name == "body-pose-frame"
        assert payload["source"] == "sse-test"
        assert payload["sequence"] == 7
        assert payload["pose"]["head_yaw"] == 0.31


def test_sse_stream_subscription_lifecycle_is_deterministic() -> None:
    with BodyPoseLabHttpHarness.start(local_simulation=False) as harness:
        subscription = harness.components.sse.open()
        assert harness.components.frame_hub.snapshot().subscriber_count == 1

        harness.components.sse.close(subscription)

        assert harness.components.frame_hub.snapshot().subscriber_count == 0


def test_local_simulation_tick_loop_starts_and_stops_without_leaking_ticks() -> None:
    with BodyPoseLabHttpHarness.start(
        local_simulation=True,
        tick_hz=30.0,
    ) as harness:
        harness.wait_until(
            lambda: harness.components.frame_hub.snapshot().received_count >= 2
        )
        assert harness.components.tick_loop.running is True

        harness.components.tick_loop.stop()
        stopped_count = harness.components.frame_hub.snapshot().received_count
        sleep(0.08)

        assert harness.components.tick_loop.running is False
        assert harness.components.frame_hub.snapshot().received_count == stopped_count
        status, health = harness.json_request("GET", "/health")
        assert status == 200
        assert health["tick_running"] is False
        assert health["tick_error"] is None
