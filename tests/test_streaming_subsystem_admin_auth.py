from fastapi.testclient import TestClient

from subsystems.streaming.admin_api import create_streaming_admin_api
from subsystems.streaming.bootstrap import build_streaming_subsystem


def test_configured_token_is_required_for_rest_and_sse() -> None:
    api = TestClient(create_streaming_admin_api(build_streaming_subsystem(), token="test-token"))
    assert api.get("/api/v1/health").status_code == 401
    assert api.get("/api/v1/events").status_code == 401
    headers = {"Authorization": "Bearer test-token"}
    assert api.get("/api/v1/health", headers=headers).status_code == 200


def test_auth_error_does_not_echo_token() -> None:
    api = TestClient(create_streaming_admin_api(build_streaming_subsystem(), token="private-value"))
    response = api.get("/api/v1/health", headers={"Authorization": "Bearer wrong-value"})
    assert "private-value" not in response.text
    assert "wrong-value" not in response.text
