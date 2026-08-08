from __future__ import annotations

from http.server import ThreadingHTTPServer

import pytest

from gui.body_pose_lab.http_transport_server import (
    BodyPoseLabThreadingHttpServer,
    is_expected_client_disconnect,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "error",
    [
        BrokenPipeError(),
        ConnectionAbortedError(),
        ConnectionResetError(),
    ],
)
def test_expected_browser_disconnects_are_classified(error: BaseException) -> None:
    assert is_expected_client_disconnect(error) is True


def test_unexpected_server_error_is_not_classified_as_disconnect() -> None:
    assert is_expected_client_disconnect(RuntimeError("unexpected")) is False


def test_http_server_suppresses_only_expected_disconnects(monkeypatch) -> None:
    delegated: list[tuple[object, object]] = []

    def record_delegate(self, request, client_address) -> None:
        del self
        delegated.append((request, client_address))

    monkeypatch.setattr(ThreadingHTTPServer, "handle_error", record_delegate)
    server = object.__new__(BodyPoseLabThreadingHttpServer)

    try:
        raise ConnectionResetError("browser closed keep-alive")
    except ConnectionResetError:
        server.handle_error("request", ("127.0.0.1", 1234))
    assert delegated == []

    try:
        raise RuntimeError("unexpected")
    except RuntimeError:
        server.handle_error("request", ("127.0.0.1", 5678))
    assert delegated == [("request", ("127.0.0.1", 5678))]
