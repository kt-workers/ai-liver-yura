"""実ポートを開かず、分割受信・拒否・資源回収の通信境界を検証する。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest

from app.config.gui_admin import load_gui_admin_config
from app.subsystems.gui_admin.http_application import GuiHttpResponse
from app.subsystems.gui_admin.http_transport import (
    GuiAdminHttpTransport,
    _RequestProtocol,
)


class Wire(asyncio.Transport):
    def __init__(self, protocol: _RequestProtocol) -> None:
        self.protocol = protocol
        self.output = bytearray()
        self.closing = False
        self.aborted = False

    def write(self, data: bytes | bytearray | memoryview[Any]) -> None:
        self.output.extend(data)

    def close(self) -> None:
        self.closing = True

    def abort(self) -> None:
        self.aborted = True
        self.closing = True
        self.protocol.connection_lost(None)


def owner() -> GuiAdminHttpTransport:
    config = load_gui_admin_config(
        Path("resources/config/v2/gui_admin.yaml").read_text()
    )
    application = Mock()
    application.respond.return_value = GuiHttpResponse(
        204, (("Connection", "close"),), b""
    )
    return GuiAdminHttpTransport(config, application)


def connect(server: GuiAdminHttpTransport) -> tuple[_RequestProtocol, Wire]:
    protocol = _RequestProtocol(server)
    wire = Wire(protocol)
    protocol.connection_made(wire)
    return protocol, wire


@pytest.mark.asyncio
@pytest.mark.parametrize("fragmented", [False, True])
async def test_success_closes_one_response_without_processing_pipeline(
    fragmented: bool,
) -> None:
    server = owner()
    protocol, wire = connect(server)
    request = b"GET /healthz HTTP/1.1\r\nHost: localhost\r\n\r\n"
    for fragment in ([bytes([byte]) for byte in request] if fragmented else [request]):
        protocol.data_received(fragment)
    protocol.data_received(request)
    assert bytes(wire.output).startswith(b"HTTP/1.1 204 ")
    assert wire.closing
    cast(Mock, server.application.respond).assert_called_once_with(
        b"GET", b"/healthz", has_body=False
    )
    await server.stop()
    assert not server.connections


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_request",
    [
        b"GET / HTTP/1.1\r\nHost: x\r\nX: " + b"z" * 8190 + b"\r\n\r\n",
        b"GET /" + b"z" * 4096 + b" HTTP/1.1\r\nHost: x\r\n\r\n",
        b"GET / HTTP/1.1\r\nHost: x\r\n" + b"X: z\r\n" * 64 + b"\r\n",
        b"GET / HTTP/1.1\r\nHost: x\r\n no-fold: z\r\n\r\n",
        b"GET / HTTP/1.1\nHost: x\n\n",
        b"GET / HTTP/1.1\r\nHost: x\r\nContent-Length: SECRET_SENTINEL\r\n\r\n",
        b"GET / HTTP/1.1\r\nHost: x\r\nHost: y\r\n\r\n",
    ],
)
async def test_parser_rejections_are_fixed_and_do_not_call_application(
    raw_request: bytes,
) -> None:
    server = owner()
    protocol, wire = connect(server)
    for position in range(0, len(raw_request), 17):
        protocol.data_received(raw_request[position : position + 17])
    assert bytes(wire.output) == (
        b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
    )
    cast(Mock, server.application.respond).assert_not_called()
    await server.stop()


@pytest.mark.asyncio
async def test_exact_bounds_allow_64_headers_and_maximum_line_lengths() -> None:
    server = owner()
    protocol, wire = connect(server)
    line = b"GET /" + b"a" * (4096 - len(b"GET / HTTP/1.1")) + b" HTTP/1.1"
    request = line + b"\r\nHost: x\r\nX: " + b"z" * (8192 - 3) + b"\r\n"
    request += b"X: z\r\n" * 62 + b"\r\n"
    protocol.data_received(request)
    assert wire.output.startswith(b"HTTP/1.1 204 ")
    cast(Mock, server.application.respond).assert_called_once()
    await server.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "header", [b"Content-Length: 1", b"Transfer-Encoding: chunked"]
)
async def test_body_is_rejected_without_waiting_for_body(header: bytes) -> None:
    server = owner()
    protocol, _ = connect(server)
    protocol.data_received(b"HEAD / HTTP/1.1\r\nHost: x\r\n" + header + b"\r\n\r\n")
    cast(Mock, server.application.respond).assert_called_once_with(
        b"HEAD", b"/", has_body=True
    )
    await server.stop()


@pytest.mark.asyncio
async def test_unsupported_transfer_encoding_is_body_rejection_without_reflection() -> (
    None
):
    server = owner()
    protocol, wire = connect(server)
    protocol.data_received(
        b"HEAD / HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: SECRET_SENTINEL\r\n\r\n"
    )
    assert wire.output.startswith(b"HTTP/1.1 413 ")
    assert bytes(wire.output).endswith(b"\r\n\r\n")
    assert b"SECRET_SENTINEL" not in wire.output
    cast(Mock, server.application.respond).assert_not_called()
    await server.stop()


@pytest.mark.asyncio
async def test_overload_has_no_queue_and_releases_capacity_on_disconnect() -> None:
    server = owner()
    accepted = [connect(server) for _ in range(16)]
    rejected, wire = connect(server)
    assert wire.output.startswith(b"HTTP/1.1 503 ")
    assert wire.aborted and rejected.closed.done()
    assert len(server.connections) == 16
    accepted[0][1].abort()
    _, replacement = connect(server)
    assert not replacement.closing
    await server.stop()
    assert all(item[1].aborted for item in accepted)
    assert not server.connections
    await server.stop()
    _, stopped = connect(server)
    assert stopped.aborted and not stopped.output


@pytest.mark.asyncio
async def test_partial_head_timeout_has_no_body_and_reclaims_connection() -> None:
    server = owner()
    server.policy = replace(server.policy, request_timeout_seconds=0.001)
    protocol, wire = connect(server)
    protocol.data_received(b"HEAD / HTTP/1.1\r\nHost:")
    await asyncio.wait_for(protocol.closed, timeout=0.5)
    assert wire.output.startswith(b"HTTP/1.1 503 ")
    assert wire.output.endswith(b"\r\n\r\n")
    assert not server.connections
    cast(Mock, server.application.respond).assert_not_called()


@pytest.mark.asyncio
async def test_server_lifecycle_uses_loopback_and_closes_after_start_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = owner()
    listener = Mock()
    listener.start_serving = AsyncMock(side_effect=OSError("非公開の待受情報"))
    listener.wait_closed = AsyncMock()
    create = AsyncMock(return_value=listener)
    monkeypatch.setattr(asyncio.get_running_loop(), "create_server", create)
    with pytest.raises(OSError):
        await server.start()
    assert create.call_args.args[1:] == ("127.0.0.1", server.config.port)
    assert create.call_args.kwargs == {"start_serving": False}
    listener.close.assert_called_once()
    listener.wait_closed.assert_awaited_once()
    await server.stop()


@pytest.mark.asyncio
async def test_transport_injected_into_subsystem_reaches_available_and_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import datetime, timezone

    from app.config.minimum_brain import load_minimum_brain_config
    from app.runtime.kernel.clock import FakeRuntimeClock
    from app.subsystems.gui_admin.contracts import GuiAdminAvailability
    from app.subsystems.gui_admin.lifecycle import GuiAdminSubsystem

    listener = Mock()
    listener.start_serving = AsyncMock()
    listener.wait_closed = AsyncMock()
    create = AsyncMock(return_value=listener)
    monkeypatch.setattr(asyncio.get_running_loop(), "create_server", create)
    brain = load_minimum_brain_config(
        Path("resources/config/v2/minimum_brain.yaml").read_text()
    )
    gui = GuiAdminSubsystem(
        owner().config,
        brain,
        FakeRuntimeClock(datetime(2026, 9, 22, tzinfo=timezone.utc)),
        GuiAdminHttpTransport,
    )
    assert (await gui.start()).availability is GuiAdminAvailability.AVAILABLE
    protocol = create.call_args.args[0]()
    wire = Wire(protocol)
    protocol.connection_made(wire)
    protocol.data_received(b"GET /healthz HTTP/1.1\r\nHost: x\r\n\r\n")
    assert wire.output.startswith(b"HTTP/1.1 204 ")
    assert (await gui.stop()).completed
    assert wire.aborted
    listener.close.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", [b"GET", b"HEAD"])
async def test_application_failure_cannot_reflect_exception(method: bytes) -> None:
    server = owner()
    cast(Mock, server.application.respond).side_effect = RuntimeError("SECRET_SENTINEL")
    protocol, wire = connect(server)
    protocol.data_received(method + b" / HTTP/1.1\r\nHost: x\r\n\r\n")
    assert wire.output.startswith(b"HTTP/1.1 500 ")
    assert b"SECRET_SENTINEL" not in wire.output
    if method == b"HEAD":
        assert wire.output.endswith(b"\r\n\r\n")
    else:
        assert b"GUI_INTERNAL_TRANSPORT_FAILURE" in wire.output
    await server.stop()
