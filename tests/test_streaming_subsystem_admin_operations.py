from fastapi.testclient import TestClient

from subsystems.streaming.admin_api import create_streaming_admin_api
from subsystems.streaming.bootstrap import build_streaming_subsystem


def test_fake_session_can_be_prepared_and_started_idempotently() -> None:
    api = TestClient(create_streaming_admin_api(build_streaming_subsystem()))
    broadcast = api.get("/api/v1/streaming/broadcasts").json()["items"][0]
    command = {
        "command_id": "prepare-1",
        "broadcast_id": broadcast["broadcast_id"],
        "run_of_show_id": "default",
    }
    first = api.post("/api/v1/streaming/session/prepare", json=command)
    assert first.status_code == 200
    assert first.json()["ready"] is True
    session = api.get("/api/v1/streaming/session").json()
    duplicate = api.post(
        "/api/v1/streaming/session/prepare",
        json={
            **command,
            "session_id": session["session_id"],
            "expected_state_version": session["state_version"],
        },
    )
    assert duplicate.json()["duplicate"] is True
    started = api.post(
        "/api/v1/streaming/session/start/approve",
        json={
            "command_id": "start-1",
            "session_id": session["session_id"],
            "expected_state_version": session["state_version"],
            "approved_by": "operator",
        },
    )
    assert started.status_code == 202
    assert started.json()["successful"] is True


def test_prepare_version_mismatch_is_conflict() -> None:
    api = TestClient(create_streaming_admin_api(build_streaming_subsystem()))
    broadcast = api.get("/api/v1/streaming/broadcasts").json()["items"][0]
    api.post(
        "/api/v1/streaming/session/prepare",
        json={
            "command_id": "prepare-1",
            "broadcast_id": broadcast["broadcast_id"],
            "run_of_show_id": "default",
        },
    )
    session = api.get("/api/v1/streaming/session").json()
    response = api.post(
        "/api/v1/streaming/session/prepare",
        json={
            "command_id": "prepare-2",
            "session_id": session["session_id"],
            "broadcast_id": broadcast["broadcast_id"],
            "run_of_show_id": "default",
            "expected_state_version": -1,
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "stream.prepare.version_mismatch"
