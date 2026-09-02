from __future__ import annotations

import json
import os
import sys
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Final, cast
from urllib.parse import urlparse

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from gui.v2_body_avatar_verification.realtime_runtime import VerificationEngine
else:
    from .realtime_runtime import VerificationEngine

MAX_JSON_BYTES: Final = 64 * 1024
WEB_ROOT: Final = Path(__file__).with_name("web")
CONTENT_TYPES: Final = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
}


class VerificationHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], engine: VerificationEngine) -> None:
        super().__init__(address, VerificationRequestHandler)
        self.engine = engine

    def handle_error(self, request: object, client_address: object) -> None:
        error = sys.exc_info()[1]
        if isinstance(error, ConnectionResetError):
            return
        super().handle_error(request, client_address)


class VerificationRequestHandler(BaseHTTPRequestHandler):
    server_version = "YuraV2BodyAvatarVerification/1"

    @property
    def verification_server(self) -> VerificationHTTPServer:
        return cast(VerificationHTTPServer, self.server)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            self._json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "service": "v2-body-avatar-verification",
                    "verification_only": True,
                    "never_merge": True,
                    "body_realtime_runtime": True,
                },
            )
            return
        if path == "/api/snapshot":
            self._json(HTTPStatus.OK, self.verification_server.engine.snapshot())
            return
        if path == "/api/events":
            self._events()
            return
        self._static(path)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/command":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        length_header = self.headers.get("Content-Length")
        if length_header is None:
            self.send_error(HTTPStatus.LENGTH_REQUIRED)
            return
        try:
            length = int(length_header)
        except ValueError:
            self.send_error(HTTPStatus.BAD_REQUEST)
            return
        if length < 0 or length > MAX_JSON_BYTES:
            self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_error(HTTPStatus.BAD_REQUEST)
            return
        if not isinstance(payload, dict) or any(not isinstance(key, str) for key in payload):
            self.send_error(HTTPStatus.BAD_REQUEST)
            return
        self.verification_server.engine.submit_command(cast(dict[str, object], payload))
        self._json(HTTPStatus.ACCEPTED, {"accepted": True})

    def _events(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            while True:
                data = json.dumps(
                    self.verification_server.engine.snapshot(),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                self.wfile.write(f"event: snapshot\ndata: {data}\n\n".encode("utf-8"))
                self.wfile.flush()
                time.sleep(0.1)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _static(self, request_path: str) -> None:
        relative = "index.html" if request_path in {"", "/"} else request_path.lstrip("/")
        candidate = (WEB_ROOT / relative).resolve()
        try:
            candidate.relative_to(WEB_ROOT.resolve())
        except ValueError:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not candidate.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = CONTENT_TYPES.get(candidate.suffix, "application/octet-stream")
        body = candidate.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: HTTPStatus, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        print(f"[v2-body-avatar-verification] {self.address_string()} {format % args}")


def main() -> None:
    host = os.environ.get("YURA_V2_BODY_AVATAR_VERIFY_HOST", "127.0.0.1")
    port = int(
        os.environ.get(
            "YURA_V2_BODY_AVATAR_VERIFY_PORT",
            os.environ.get("PORT", "8769"),
        )
    )
    tick_hz = float(os.environ.get("YURA_V2_BODY_AVATAR_VERIFY_TICK_HZ", "30"))
    engine = VerificationEngine(tick_hz=tick_hz)
    engine.start()
    server = VerificationHTTPServer((host, port), engine)
    print(f"#341/#346 Browser Verification: http://{host}:{port}")
    print("#340 BodyRealtimeRuntime connected / verification-only / PR #544 NEVER MERGE")
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        engine.stop()


if __name__ == "__main__":
    main()
