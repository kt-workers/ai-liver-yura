from __future__ import annotations

from tests.support.body_pose_lab_http_harness import BodyPoseLabHttpHarness


def test_real_http_server_rejects_invalid_json_and_oversized_payload() -> None:
    with BodyPoseLabHttpHarness.start(
        local_simulation=False,
        maximum_json_bytes=2048,
    ) as harness:
        invalid_status, invalid = harness.raw_json_request(
            "POST",
            "/api/emotion",
            data=b"{not-json",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        oversized_status, oversized = harness.raw_json_request(
            "POST",
            "/api/emotion",
            data=b"x" * 2049,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    assert invalid_status == 400
    assert invalid["error"] == "invalid_json"
    assert oversized_status == 413
    assert oversized["error"] == "payload_too_large"
