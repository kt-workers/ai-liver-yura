from __future__ import annotations

import ssl
from concurrent.futures import ThreadPoolExecutor

import pytest

from tools.character_reference_analysis import google_drive


class FakeHttp:
    pass


class FakeAuthorizedHttp:
    def __init__(self, credentials: object, *, http: object) -> None:
        self.credentials = credentials
        self.http = http


class FakeRequest:
    def __init__(self, http: object, *args: object, **kwargs: object) -> None:
        del args, kwargs
        self.http = http


def test_drive_request_builder_keeps_http_transport_thread_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credentials = object()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        google_drive,
        "build_google_drive_credentials",
        lambda **_kwargs: credentials,
    )
    monkeypatch.setattr(google_drive.httplib2, "Http", FakeHttp)
    monkeypatch.setattr(google_drive, "AuthorizedHttp", FakeAuthorizedHttp)
    monkeypatch.setattr(google_drive, "HttpRequest", FakeRequest)

    def fake_build(
        service_name: str,
        version: str,
        **kwargs: object,
    ) -> object:
        assert service_name == "drive"
        assert version == "v3"
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(google_drive, "build", fake_build)

    google_drive.build_google_drive_service()
    request_builder = captured["requestBuilder"]
    assert callable(request_builder)

    first = request_builder(None)
    second = request_builder(None)
    with ThreadPoolExecutor(max_workers=1) as executor:
        worker = executor.submit(request_builder, None).result()

    assert isinstance(first, FakeRequest)
    assert isinstance(second, FakeRequest)
    assert isinstance(worker, FakeRequest)
    assert first.http is second.http
    assert worker.http is not first.http


def test_drive_ssl_retry_recovers_from_transient_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0
    monkeypatch.setattr(google_drive.time, "sleep", lambda _seconds: None)

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ssl.SSLError("bad record mac")
        return "ok"

    assert google_drive._call_with_ssl_retry(operation) == "ok"
    assert attempts == 2


def test_drive_ssl_retry_does_not_hide_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0
    monkeypatch.setattr(google_drive.time, "sleep", lambda _seconds: None)

    def operation() -> None:
        nonlocal attempts
        attempts += 1
        raise ssl.SSLError("bad record mac")

    with pytest.raises(ssl.SSLError, match="bad record mac"):
        google_drive._call_with_ssl_retry(operation)

    assert attempts == google_drive._DRIVE_SSL_MAX_ATTEMPTS
