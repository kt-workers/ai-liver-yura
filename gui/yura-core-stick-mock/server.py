from __future__ import annotations

import json
import mimetypes
import os
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

WEB_ROOT = Path(__file__).resolve().parent / "web"
SHARED_SKELETON = (
    Path(__file__).resolve().parents[1]
    / "yura-body-pose-lab"
    / "web"
    / "body-pose-skeleton.js"
)
MAX_BODY_BYTES = 1_048_576


class CoreStickMockHub:
    """Coreから届いた最新BodyPoseFrameだけを保持する。"""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._payload: dict[str, object] | None = None
        self._stream_sequence = 0
        self._received_at: float | None = None

    def publish(self, payload: object) -> dict[str, object]:
        normalized = self._validate(payload)
        with self._condition:
            self._payload = normalized
            self._stream_sequence += 1
            self._received_at = time.monotonic()
            self._condition.notify_all()
        return normalized

    def snapshot(self) -> dict[str, object] | None:
        with self._condition:
            return dict(self._payload) if self._payload is not None else None

    def status_payload(self) -> dict[str, object]:
        with self._condition:
            age_ms = (
                None
                if self._received_at is None
                else max(0, round((time.monotonic() - self._received_at) * 1000))
            )
            return {
                "status": "ok",
                "source": "yura-core" if self._payload is not None else "waiting",
                "stream_sequence": self._stream_sequence,
                "frame_sequence": (
                    self._payload.get("sequence")
                    if self._payload is not None
                    else None
                ),
                "last_frame_age_ms": age_ms,
            }

    def wait_for_payload(
        self,
        after_stream_sequence: int,
        *,
        timeout: float = 2.0,
    ) -> tuple[int, dict[str, object] | None]:
        with self._condition:
            self._condition.wait_for(
                lambda: self._stream_sequence > after_stream_sequence,
                timeout=timeout,
            )
            payload = dict(self._payload) if self._payload is not None else None
            return self._stream_sequence, payload

    @staticmethod
    def _validate(payload: object) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("BodyPoseFrame must be an object")
        required_objects = (
            "pose",
            "velocity",
            "inner_state",
            "root_transform",
        )
        for name in required_objects:
            if not isinstance(payload.get(name), dict):
                raise ValueError(f"{name} must be an object")
        for name in ("joints", "blend_shapes"):
            if not isinstance(payload.get(name), list):
                raise ValueError(f"{name} must be an array")
        sequence = payload.get("sequence")
        timestamp_ms = payload.get("timestamp_ms")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise ValueError("sequence must be a non-negative integer")
        if (
            isinstance(timestamp_ms, bool)
            or not isinstance(timestamp_ms, int)
            or timestamp_ms < 0
        ):
            raise ValueError("timestamp_ms must be a non-negative integer")
        schema_version = payload.get("schema_version")
        if schema_version != 2:
            raise ValueError("schema_version must be 2")
        normalized = dict(payload)
        normalized["type"] = "body.pose.frame"
        normalized["source"] = str(payload.get("source") or "yura-core")[:80]
        return normalized


HUB = CoreStickMockHub()


class CoreStickMockHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            self._json_response(HTTPStatus.OK, HUB.status_payload())
            return
        if path == "/api/snapshot":
            payload = HUB.snapshot()
            if payload is None:
                self._json_response(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"status": "waiting", "message": "Core Frame待機中"},
                )
            else:
                self._json_response(HTTPStatus.OK, payload)
            return
        if path == "/api/frames":
            self._stream_frames()
            return
        if path == "/":
            self._serve_static("index.html")
            return
        if path == "/body-pose-skeleton.js":
            self._serve_file(SHARED_SKELETON)
            return
        if path.startswith("/"):
            self._serve_static(path[1:])
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/body-pose-frame":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            payload = HUB.publish(self._read_json())
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            self._json_response(
                HTTPStatus.BAD_REQUEST,
                {"status": "error", "message": str(error)},
            )
            return
        self._json_response(
            HTTPStatus.ACCEPTED,
            {
                "status": "accepted",
                "sequence": payload["sequence"],
            },
        )

    def log_message(self, format: str, *args: object) -> None:
        print(f"[core-stick-mock] {self.address_string()} {format % args}")

    def _stream_frames(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        stream_sequence = 0
        try:
            while True:
                next_sequence, payload = HUB.wait_for_payload(
                    stream_sequence,
                    timeout=1.5,
                )
                if payload is None or next_sequence <= stream_sequence:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                    continue
                stream_sequence = next_sequence
                data = json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                self.wfile.write(b"event: body-pose-frame\n")
                self.wfile.write(b"data: " + data + b"\n\n")
                self.wfile.flush()
        except (
            BrokenPipeError,
            ConnectionResetError,
            ConnectionAbortedError,
            TimeoutError,
        ):
            return

    def _serve_static(self, relative_path: str) -> None:
        target = (WEB_ROOT / relative_path).resolve()
        try:
            target.relative_to(WEB_ROOT.resolve())
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._serve_file(target)

    def _serve_file(self, target: Path) -> None:
        if not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content = target.read_bytes()
        content_type, _ = mimetypes.guess_type(target.name)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content)

    def _read_json(self) -> object:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError as error:
            raise ValueError("invalid Content-Length") from error
        if length < 0 or length > MAX_BODY_BYTES:
            raise ValueError("request body is too large")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _json_response(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)


class QuietDisconnectHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request: Any, client_address: Any) -> None:
        _ = request, client_address
        error = __import__("sys").exc_info()[1]
        if isinstance(
            error,
            (BrokenPipeError, ConnectionResetError, ConnectionAbortedError),
        ):
            return
        super().handle_error(request, client_address)


def main() -> None:
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8010"))
    server = QuietDisconnectHTTPServer((host, port), CoreStickMockHandler)
    print(f"Core Stick Mock listening on http://{host}:{port}")
    print("YURA_BODY_POSE_OUTPUT_URLをこのURLへ設定してCoreを起動してください。")
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
