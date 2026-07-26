from __future__ import annotations

import argparse
import json
import mimetypes
import socket
import threading
import time
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import monotonic
from typing import Any
from urllib.parse import urlparse

WEB_ROOT = Path(__file__).parent / "web"
MAX_STIMULUS_BODY_BYTES = 2048


class StimulusGateway:
    """検証済みの画面刺激だけをCoreのローカル入力境界へ転送する。"""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        minimum_interval_seconds: float = 0.75,
        send_datagram: Callable[[bytes, tuple[str, int]], None] | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._minimum_interval_seconds = minimum_interval_seconds
        self._send_datagram = send_datagram or self._send_udp
        self._lock = threading.Lock()
        self._last_sent_at = -minimum_interval_seconds

    def send_tap(self, x: float, y: float) -> bool:
        now = monotonic()
        with self._lock:
            if now - self._last_sent_at < self._minimum_interval_seconds:
                return False
            self._last_sent_at = now
        packet = json.dumps(
            {
                "schema_version": 1,
                "type": "interaction_stimulus",
                "stimulus_kind": "tap",
                "position": {"x": x, "y": y},
            },
            separators=(",", ":"),
        ).encode("utf-8")
        self._send_datagram(packet, (self._host, self._port))
        return True

    @staticmethod
    def _send_udp(packet: bytes, address: tuple[str, int]) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            sender.sendto(packet, address)


class StateHub:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._sequence = 0
        self._latest: dict[str, Any] | None = None

    def publish(self, state: dict[str, Any]) -> None:
        with self._condition:
            self._sequence += 1
            self._latest = state
            self._condition.notify_all()

    def snapshot(self) -> tuple[int, dict[str, Any] | None]:
        with self._condition:
            return self._sequence, self._latest

    def wait_next(self, sequence: int, timeout: float) -> tuple[int, dict[str, Any] | None]:
        with self._condition:
            self._condition.wait_for(lambda: self._sequence > sequence, timeout)
            return self._sequence, self._latest


class TelemetryReceiver(threading.Thread):
    def __init__(self, hub: StateHub, host: str, port: int) -> None:
        super().__init__(name="YuraTelemetryReceiver", daemon=True)
        self._hub = hub
        self._host = host
        self._port = port

    def run(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.bind((self._host, self._port))
            while True:
                data, _ = receiver.recvfrom(65535)
                try:
                    payload = json.loads(data.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if self._valid(payload):
                    self._hub.publish(payload)

    @staticmethod
    def _valid(value: object) -> bool:
        return (
            isinstance(value, dict)
            and value.get("schema_version") == 1
            and isinstance(value.get("emotion"), dict)
            and isinstance(value.get("drive"), dict)
        )


def handler_for(
    hub: StateHub,
    stimulus_gateway: StimulusGateway | None = None,
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "YuraInnerState/1.0"

        def handle(self) -> None:
            try:
                super().handle()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                # Browsers may discard a pre-opened or replaced connection before
                # sending the next request. This is a normal client disconnect.
                return

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/events":
                self._events()
                return
            if path == "/state":
                _, state = hub.snapshot()
                self._json(state or {"status": "waiting"})
                return
            self._static(path)

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/api/stimuli":
                self._stimulus()
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def _stimulus(self) -> None:
            payload = self._read_json()
            if payload is None or payload.get("kind") != "tap":
                self._json(
                    {"status": "rejected", "reason": "invalid_stimulus"},
                    HTTPStatus.BAD_REQUEST,
                )
                return
            x = payload.get("x")
            y = payload.get("y")
            if not self._normalized_number(x) or not self._normalized_number(y):
                self._json(
                    {"status": "rejected", "reason": "invalid_position"},
                    HTTPStatus.BAD_REQUEST,
                )
                return
            if stimulus_gateway is None:
                self._json(
                    {"status": "unavailable"},
                    HTTPStatus.SERVICE_UNAVAILABLE,
                )
                return
            try:
                accepted = stimulus_gateway.send_tap(float(x), float(y))
            except OSError:
                self._json(
                    {"status": "unavailable"},
                    HTTPStatus.SERVICE_UNAVAILABLE,
                )
                return
            if not accepted:
                self._json(
                    {"status": "throttled"},
                    HTTPStatus.TOO_MANY_REQUESTS,
                )
                return
            self._json({"status": "accepted"}, HTTPStatus.ACCEPTED)

        def _read_json(self) -> dict[str, Any] | None:
            raw_length = self.headers.get("Content-Length", "")
            try:
                length = int(raw_length)
            except ValueError:
                return None
            if length <= 0 or length > MAX_STIMULUS_BODY_BYTES:
                return None
            try:
                value = json.loads(self.rfile.read(length))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return None
            return value if isinstance(value, dict) else None

        @staticmethod
        def _normalized_number(value: object) -> bool:
            return (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and 0.0 <= float(value) <= 1.0
            )

        def _events(self) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            sequence, state = hub.snapshot()
            try:
                if state is not None:
                    self._send_event(state)
                while True:
                    next_sequence, next_state = hub.wait_next(sequence, 15.0)
                    if next_sequence == sequence:
                        self.wfile.write(b": heartbeat\n\n")
                    elif next_state is not None:
                        sequence = next_sequence
                        self._send_event(next_state)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return

        def _send_event(self, state: dict[str, Any]) -> None:
            body = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
            self.wfile.write(f"event: state\ndata: {body}\n\n".encode())

        def _json(
            self,
            value: dict[str, Any],
            status: HTTPStatus = HTTPStatus.OK,
        ) -> None:
            body = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _static(self, path: str) -> None:
            relative = "index.html" if path == "/" else path.lstrip("/")
            target = (WEB_ROOT / relative).resolve()
            if WEB_ROOT.resolve() not in target.parents and target != WEB_ROOT.resolve():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if not target.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            body = target.read_bytes()
            content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            if "/events" not in str(args):
                super().log_message(format, *args)

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Yura inner-state visualizer")
    parser.add_argument("--http-host", default="127.0.0.1")
    parser.add_argument("--http-port", type=int, default=8765)
    parser.add_argument("--udp-host", default="127.0.0.1")
    parser.add_argument("--udp-port", type=int, default=8766)
    parser.add_argument("--input-host", default="127.0.0.1")
    parser.add_argument("--input-port", type=int, default=8771)
    args = parser.parse_args()

    hub = StateHub()
    TelemetryReceiver(hub, args.udp_host, args.udp_port).start()
    server = ThreadingHTTPServer(
        (args.http_host, args.http_port),
        handler_for(
            hub,
            StimulusGateway(args.input_host, args.input_port),
        ),
    )
    print(f"Yura inner state: http://{args.http_host}:{args.http_port}")
    print(f"Telemetry UDP: {args.udp_host}:{args.udp_port}")
    print(f"Interaction UDP: {args.input_host}:{args.input_port}")
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        time.sleep(0.05)


if __name__ == "__main__":
    main()
