from __future__ import annotations

import json
import mimetypes
import os
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"


class BodyFrameHub:
    """Coreから受信した最新BodyPoseFrameだけをブラウザへ中継する。"""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._revision = 0
        self._received_at = 0.0
        self._frame: dict[str, object] = {
            "type": "body.pose.frame",
            "source": "none",
            "schema_version": 2,
            "sequence": 0,
            "pose": None,
            "blend_shapes": [],
            "joints": [],
        }

    def update(self, frame: dict[str, object]) -> int:
        with self._condition:
            self._revision += 1
            self._received_at = time.time()
            self._frame = dict(frame)
            self._condition.notify_all()
            return self._revision

    def snapshot(self) -> dict[str, object]:
        with self._condition:
            return {
                "revision": self._revision,
                "received_at": self._received_at,
                "frame": dict(self._frame),
            }

    def wait_for_update(self, revision: int, timeout: float = 20.0) -> dict[str, object]:
        with self._condition:
            if self._revision <= revision:
                self._condition.wait(timeout=timeout)
            return self.snapshot()


HUB = BodyFrameHub()


class Handler(BaseHTTPRequestHandler):
    server_version = "YuraCoreLivingBodyMock/1.0"

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/health":
            self._json(
                HTTPStatus.OK,
                {
                    "healthy": True,
                    "service": "yura-core-stick-mock",
                    "role": "body-pose-frame-renderer-only",
                    "renders": ["face", "gaze", "pose", "breathing", "speech"],
                },
            )
            return
        if path == "/api/state":
            self._json(HTTPStatus.OK, HUB.snapshot())
            return
        if path == "/api/events":
            self._events()
            return
        if path == "/":
            self._static("index.html")
            return
        self._static(path.lstrip("/"))

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path != "/api/body-pose-frame":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        try:
            payload = self._read_json()
            if not isinstance(payload, dict):
                raise ValueError("body pose frame must be an object")
            if payload.get("type") not in {None, "body.pose.frame"}:
                raise ValueError("unsupported frame type")
            if payload.get("pose") is not None and not isinstance(payload["pose"], dict):
                raise ValueError("pose must be an object")
            revision = HUB.update({str(key): value for key, value in payload.items()})
        except (ValueError, json.JSONDecodeError) as error:
            self._json(
                HTTPStatus.BAD_REQUEST,
                {"error": "invalid_body_pose_frame", "detail": str(error)},
            )
            return
        self._json(HTTPStatus.ACCEPTED, {"accepted": True, "revision": revision})

    def _events(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        revision = -1
        try:
            while True:
                snapshot = HUB.wait_for_update(revision)
                next_revision = int(snapshot["revision"])
                if next_revision == revision:
                    self.wfile.write(b": keep-alive\n\n")
                else:
                    revision = next_revision
                    body = json.dumps(
                        snapshot,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                    self.wfile.write(b"event: body-pose-frame\n")
                    self.wfile.write(b"data: " + body + b"\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return

    def _read_json(self) -> object:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 2_000_000:
            raise ValueError("invalid content length")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _static(self, relative_path: str) -> None:
        candidate = (WEB_ROOT / relative_path).resolve()
        try:
            candidate.relative_to(WEB_ROOT.resolve())
        except ValueError:
            self._json(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
            return
        if not candidate.is_file():
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        content = candidate.read_bytes()
        content_type, _ = mimetypes.guess_type(candidate.name)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def _json(self, status: HTTPStatus, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        print(f"[living-body-mock] {self.address_string()} {format % args}")


def main() -> None:
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8010"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Yura Core Living Body Mock: http://{host}:{port}")
    print("This process renders BodyPoseFrame generated by Core; it makes no decisions.")
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
