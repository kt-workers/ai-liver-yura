from __future__ import annotations

from tests.support.body_pose_lab_http_harness import BodyPoseLabHttpHarness


def test_real_http_server_exposes_health_snapshot_and_static_assets() -> None:
    with BodyPoseLabHttpHarness.start(local_simulation=False) as harness:
        health_status, health = harness.json_request("GET", "/health")
        snapshot_status, snapshot = harness.json_request("GET", "/api/snapshot")
        index_status, index_type, index = harness.bytes_request("/")
        script_status, script_type, script = harness.bytes_request("/js/main.js")
        css_status, css_type, css = harness.bytes_request("/styles.css")

    assert health_status == 200
    assert health["status"] == "ok"
    assert health["tick_running"] is False
    assert snapshot_status == 200
    assert snapshot["frames"]["received_count"] == 0
    assert index_status == 200
    assert index_type.startswith("text/html")
    assert "からだの水鏡" in index.decode("utf-8")
    assert script_status == 200
    assert "javascript" in script_type
    assert b"BodyPoseFrameStream" in script
    assert css_status == 200
    assert css_type.startswith("text/css")
    assert b".stage" in css


def test_real_http_server_returns_finite_public_errors() -> None:
    with BodyPoseLabHttpHarness.start(local_simulation=False) as harness:
        status, payload = harness.json_request("GET", "/api/not-available")
        asset_status, asset_type, asset_body = harness.bytes_request(
            "/%2e%2e/secret.txt"
        )

    assert status == 404
    assert payload == {
        "error": "not_found",
        "message": "route is not available",
    }
    assert asset_status == 404
    assert asset_type.startswith("application/json")
    assert b"asset is not available" in asset_body
