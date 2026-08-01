import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).parents[1] / "gui" / "yura-streaming-admin"
sys.path.insert(0, str(ROOT))

from client import (  # noqa: E402
    StreamingSubsystemApiClient,
    StreamingSubsystemApiError,
)

from config import StreamingSubsystemAdminConfig  # noqa: E402


def response(status: int, payload: dict[str, object]) -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request("GET", "http://test"))


def test_client_uses_subsystem_url_and_auth_header(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, object] = {}

    def request(method: str, url: str, **kwargs: object) -> httpx.Response:
        observed.update(method=method, url=url, **kwargs)
        return response(200, {"status": "available"})

    monkeypatch.setattr(httpx, "request", request)
    client = StreamingSubsystemApiClient(
        StreamingSubsystemAdminConfig("http://subsystem:8781", "test-token")
    )
    client.health()
    assert observed["url"] == "http://subsystem:8781/api/v1/health"
    assert observed["headers"] == {"Authorization": "Bearer test-token"}


@pytest.mark.parametrize("status", [401, 409, 503])
def test_client_preserves_error_status(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    monkeypatch.setattr(
        httpx,
        "request",
        lambda *args, **kwargs: response(
            status,
            {"error": {"code": "streaming.test", "message": "failed"}},
        ),
    )
    with pytest.raises(StreamingSubsystemApiError) as captured:
        StreamingSubsystemApiClient(StreamingSubsystemAdminConfig()).health()
    assert captured.value.status_code == status
