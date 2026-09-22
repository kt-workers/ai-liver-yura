"""有界のHTTP受付と固定エラー応答を、asyncioとh11の公開APIで所有する。"""

from __future__ import annotations

import asyncio
from typing import cast

import h11

from app.config.gui_admin import GuiAdminProductionConfig

from .http_application import GuiHttpApplication, GuiHttpResponse, failure_response

_PARSE_FAILURE = (
    b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
)


def _wire(response: GuiHttpResponse) -> bytes:
    """固定ヘッダーと安全な本文だけを送信形式へ変換する。"""
    headers = "\r\n".join(f"{key}: {value}" for key, value in response.headers)
    return (
        f"HTTP/1.1 {response.status} \r\n{headers}\r\n\r\n".encode("ascii")
        + response.body
    )


class _RequestProtocol(asyncio.Protocol):
    def __init__(self, owner: GuiAdminHttpTransport) -> None:
        self.owner = owner
        self.transport: asyncio.Transport | None = None
        self.timer: asyncio.TimerHandle | None = None
        self.partial = bytearray()
        self.lines: list[bytes] = []
        self.finished = False
        self.head = False
        self.closed: asyncio.Future[None] = asyncio.get_running_loop().create_future()

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = cast(asyncio.Transport, transport)
        if self.owner.closing:
            self.finished = True
            self.transport.abort()
            return
        if len(self.owner.connections) >= self.owner.policy.max_concurrent_requests:
            self.owner.closing_connections.add(self)
            self._reply(
                _wire(failure_response(503, "GUI_REQUEST_LIMIT_REACHED", head=True))
            )
            return
        self.owner.connections.add(self)
        self.timer = asyncio.get_running_loop().call_later(
            self.owner.policy.request_timeout_seconds, self._timeout
        )

    def _timeout(self) -> None:
        if self.transport is None:
            return
        if not self.finished:
            self._reply(
                _wire(failure_response(503, "GUI_REQUEST_TIMED_OUT", head=self.head))
            )

    def _reply(self, content: bytes) -> None:
        if self.finished or self.transport is None:
            return
        self.finished = True
        if self.timer is not None:
            self.timer.cancel()
        self.partial.clear()
        self.lines.clear()
        self.transport.write(content)
        self.transport.close()

    def data_received(self, data: bytes) -> None:
        if self.finished or self.owner.closing:
            return
        try:
            self._receive(data)
        except (h11.RemoteProtocolError, ValueError):
            self._reply(_PARSE_FAILURE)
        except Exception:
            self._reply(
                _wire(
                    failure_response(
                        500, "GUI_INTERNAL_TRANSPORT_FAILURE", head=self.head
                    )
                )
            )

    def _receive(self, data: bytes) -> None:
        offset = 0
        while offset < len(data) and not self.finished:
            limit = (
                self.owner.policy.max_header_field_bytes
                if self.lines
                else self.owner.policy.max_request_line_bytes
            )
            newline = data.find(b"\n", offset)
            end = len(data) if newline < 0 else newline + 1
            if len(self.partial) + end - offset > limit + 2:
                raise ValueError("HTTP行の上限超過")
            self.partial.extend(data[offset:end])
            offset = end
            if newline < 0:
                return
            line = bytes(self.partial)
            self.partial.clear()
            if not line.endswith(b"\r\n") or len(line) - 2 > limit:
                raise ValueError("HTTP行の形式が不正です")
            if not self.lines:
                self.head = line.startswith(b"HEAD ")
            if line == b"\r\n":
                self._request()
                return
            if self.lines and (line.startswith((b" ", b"\t")) or b":" not in line):
                raise ValueError("HTTPヘッダーの形式が不正です")
            if len(self.lines) > self.owner.policy.max_header_count:
                raise ValueError("HTTPヘッダーの件数超過")
            self.lines.append(line)

    def _request(self) -> None:
        if not self.lines:
            raise ValueError("HTTP要求行が必要です")
        connection = h11.Connection(h11.SERVER)
        connection.receive_data(b"".join(self.lines) + b"\r\n")
        try:
            event = connection.next_event()
        except h11.RemoteProtocolError as error:
            if error.error_status_hint == 501:
                self._reply(
                    _wire(
                        failure_response(
                            413, "GUI_REQUEST_BODY_NOT_ALLOWED", head=self.head
                        )
                    )
                )
                return
            raise
        if not isinstance(event, h11.Request) or event.http_version not in (
            b"1.0",
            b"1.1",
        ):
            raise ValueError("HTTP要求の形式が不正です")
        self.head = event.method == b"HEAD"
        has_body = any(
            key == b"transfer-encoding" or (key == b"content-length" and int(value) > 0)
            for key, value in event.headers
        )
        response = self.owner.application.respond(
            event.method, event.target, has_body=has_body
        )
        self._reply(_wire(response))

    def connection_lost(self, exc: Exception | None) -> None:
        self.finished = True
        self.partial.clear()
        self.lines.clear()
        if self.timer is not None:
            self.timer.cancel()
        self.owner.connections.discard(self)
        self.owner.closing_connections.discard(self)
        if not self.closed.done():
            self.closed.set_result(None)


class GuiAdminHttpTransport:
    """明示的な構成で待受を開始し、停止時に自分の接続だけを回収する。"""

    def __init__(
        self, config: GuiAdminProductionConfig, application: GuiHttpApplication
    ) -> None:
        self.config = config
        self.policy = config.gui_http_transport_policy
        self.application = application
        self.connections: set[_RequestProtocol] = set()
        self.closing_connections: set[_RequestProtocol] = set()
        self.closing = False
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        if self.closing:
            raise RuntimeError("停止済みのGUI通信は再起動できません")
        if self._server is not None:
            return
        server = await asyncio.get_running_loop().create_server(
            lambda: _RequestProtocol(self),
            self.config.bind_host,
            self.config.port,
            start_serving=False,
        )
        self._server = server
        try:
            if self.closing:
                raise RuntimeError("GUI通信の起動中に停止しました")
            await server.start_serving()
        except BaseException:
            server.close()
            await server.wait_closed()
            raise

    async def stop(self) -> None:
        self.closing = True
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        pending = tuple(self.connections | self.closing_connections)
        for connection in pending:
            if connection.transport is not None:
                connection.transport.abort()
        if pending:
            _, incomplete = await asyncio.wait(
                [connection.closed for connection in pending],
                timeout=self.policy.shutdown_grace_seconds,
            )
            if incomplete:
                raise RuntimeError("GUI接続の停止が期限を超過しました")
