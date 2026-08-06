from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from gui.body_pose_lab.api_controller import BodyPoseLabApiController
from gui.body_pose_lab.sse_stream import BodyPoseLabSseStream
from gui.body_pose_lab.static_files import BodyPoseLabStaticFiles

_MAX_JSON_BYTES = 512 * 1024


class BodyPoseLabHttpServer:
    """Socket／HTTP入出力だけを担当するBody Pose Lab Server。"""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        api: BodyPoseLabApiController,
        sse: BodyPoseLabSseStream,
        static_files: BodyPoseLabStaticFiles,
        maximum_json_bytes: int = _MAX_JSON_BYTES,
    ) -> None:
        if not isinstance(host, str) or not host.strip():
            raise ValueError("host must not be empty")
        if isinstance(port, bool) or not isinstance(port, int):
            raise TypeError("port must be an integer")
        if not 0 <= port <= 65_535:
            raise ValueError("port must be between 0 and 65535")
        if not 1024 <= maximum_json_bytes <= 4 * 1024 * 1024:
            raise ValueError("maximum_json_bytes is outside the supported range")
        self._api = api
        self._sse = sse
        self._static_files = static_files
        self._maximum_json_bytes = maximum_json_bytes
        self._server = ThreadingHTTPServer(
            (host.strip(), port),
            self._handler_type(),
        )
        self._server.daemon_threads = True
        self._closed = False

    @property
    def address(self) -> tuple[str, int]:
        host, port = self._server.server_address[:2]
        return str(host), int(port)

    def serve_forever(self) -> None:
        self._server.serve_forever(poll_interval=0.2)

    def shutdown(self) -> None:
        if self._closed:
            return
        self._server.shutdown()
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._server.server_close()

    def _handler_type(self) -> type[BaseHTTPRequestHandler]:
        api = self._api
        sse = self._sse
        static_files = self._static_files
        maximum_json_bytes = self._maximum_json_bytes

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self) -> None:  # noqa: N802
                path = urlsplit(self.path).path
                if path == "/api/frames":
                    self._serve_sse()
                    return
                if path == "/health" or path.startswith("/api/"):
                    self._write_api(api.handle("GET", path))
                    return
                static_file = static_files.resolve(self.path)
                if static_file is None:
                    self._write_json(
                        404,
                        {"error": "not_found", "message": "asset is not available"},
                    )
                    return
                self.send_response(200)
                self.send_header("Content-Type", static_file.content_type)
                self.send_header("Content-Length", str(len(static_file.content)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(static_file.content)

            def do_POST(self) -> None:  # noqa: N802
                path = urlsplit(self.path).path
                payload = self._read_json()
                if payload is _INVALID_JSON:
                    return
                self._write_api(api.handle("POST", path, payload))

            def do_DELETE(self) -> None:  # noqa: N802
                path = urlsplit(self.path).path
                self._write_api(api.handle("DELETE", path))

            def _read_json(self) -> object:
                raw_length = self.headers.get("Content-Length", "0")
                try:
                    length = int(raw_length)
                except ValueError:
                    self._write_json(
                        400,
                        {"error": "invalid_request", "message": "invalid content length"},
                    )
                    return _INVALID_JSON
                if length <= 0:
                    self._write_json(
                        400,
                        {"error": "invalid_request", "message": "JSON body is required"},
                    )
                    return _INVALID_JSON
                if length > maximum_json_bytes:
                    self._write_json(
                        413,
                        {"error": "payload_too_large", "message": "JSON body is too large"},
                    )
                    return _INVALID_JSON
                try:
                    return json.loads(self.rfile.read(length).decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._write_json(
                        400,
                        {"error": "invalid_json", "message": "request body is not valid JSON"},
                    )
                    return _INVALID_JSON

            def _write_api(self, response: Any) -> None:
                self._write_json(response.status, response.payload)

            def _write_json(self, status: int, payload: dict[str, object]) -> None:
                body = json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _serve_sse(self) -> None:
                try:
                    subscription = sse.open()
                except RuntimeError:
                    self._write_json(
                        503,
                        {"error": "subscriber_limit", "message": "stream limit reached"},
                    )
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                try:
                    for event in sse.events(subscription):
                        self.wfile.write(event)
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, TimeoutError):
                    pass
                finally:
                    sse.close(subscription)

            def log_message(self, format: str, *args: object) -> None:
                del format, args

        return Handler


_INVALID_JSON = object()
