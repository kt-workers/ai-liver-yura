from fastapi.testclient import TestClient

from subsystems.streaming.admin_api import create_streaming_admin_api
from subsystems.streaming.bootstrap import build_streaming_subsystem


def test_public_integration_routes_are_separate_from_admin_read_models() -> None:
    client = TestClient(create_streaming_admin_api(build_streaming_subsystem()))
    assert client.get("/api/v1/integration/version").json() == {"major": 1, "minor": 0}
    assert client.get("/api/v1/integration/status").status_code == 200
    health = client.get("/api/v1/integration/health").json()
    assert set(health) >= {"status", "healthy", "checked_at", "components"}
    assert client.get("/api/v1/integration/capabilities").status_code == 200
    dependencies = client.get("/api/v1/integration/dependencies/health").json()
    assert isinstance(dependencies["items"], list)


def test_public_operation_keeps_idempotency_key() -> None:
    client = TestClient(create_streaming_admin_api(build_streaming_subsystem()))
    response = client.post(
        "/api/v1/integration/operations",
        json={
            "operation_id": "operation-1",
            "operation_type": "prepare",
            "payload": {},
            "idempotency_key": "same-request",
        },
    )
    assert response.status_code == 200
    assert response.json()["operation_id"] == "operation-1"
