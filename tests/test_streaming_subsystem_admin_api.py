from fastapi.testclient import TestClient

from subsystems.streaming.admin_api import create_streaming_admin_api
from subsystems.streaming.bootstrap import build_streaming_subsystem


def client() -> TestClient:
    return TestClient(create_streaming_admin_api(build_streaming_subsystem()))


def test_health_status_capability_and_dependencies_work_without_core() -> None:
    api = client()
    health = api.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["api_version"] == "1.0"
    assert health.json()["event_stream_available"] is True
    assert api.get("/api/v1/status").status_code == 200
    assert api.get("/api/v1/capabilities").json()["items"]
    dependencies = api.get("/api/v1/dependencies/health").json()["items"]
    core = {item["kind"]: item for item in dependencies if item["kind"].startswith("core_")}
    assert core["core_content_execution"]["state"] == "disconnected"
    assert core["core_comment_decision"]["state"] == "disconnected"


def test_no_session_is_a_normal_not_found_response() -> None:
    response = client().get("/api/v1/streaming/session")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "stream.session.not_found"


def test_responses_do_not_expose_private_adapter_state() -> None:
    payload = client().get("/api/v1/admin/console").text.lower()
    assert "access_token" not in payload
    assert "refresh_token" not in payload
    assert "live_chat_id" not in payload
