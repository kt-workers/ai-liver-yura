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
SUPPORTED_STIMULI = frozenset({"tap", "double_tap", "long_press", "drag"})
DRAG_STREAM_PHASES = frozenset({"start", "update", "end"})


class StimulusGateway:
    """検証済みの画面刺激だけをCoreのローカル入力境界へ転送する。"""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        minimum_interval_seconds: float = 0.75,
        drag_stream_minimum_interval_seconds: float = 0.10,
        send_datagram: Callable[[bytes, tuple[str, int]], None] | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._minimum_interval_seconds = minimum_interval_seconds
        self._drag_stream_minimum_interval_seconds = drag_stream_minimum_interval_seconds
        self._send_datagram = send_datagram or self._send_udp
        self._lock = threading.Lock()
        self._last_sent_at_by_kind: dict[str, float] = {}

    def send_tap(self, x: float, y: float) -> bool:
        return self.send_stimulus("tap", x, y)

    def send_stimulus(
        self,
        kind: str,
        x: float,
        y: float,
        *,
        start_position: tuple[float, float] | None = None,
        duration_ms: float | None = None,
        gesture_id: str | None = None,
        gesture_phase: str | None = None,
        gesture_sequence: int | None = None,
        particle_zone: dict[str, object] | None = None,
    ) -> bool:
        if kind not in SUPPORTED_STIMULI:
            return False
        now = monotonic()
        is_drag_stream = (
            kind == "drag"
            and gesture_id is not None
            and gesture_phase in DRAG_STREAM_PHASES
            and gesture_sequence is not None
        )
        rate_limit_key = f"drag:{gesture_id}" if is_drag_stream else kind
        minimum_interval = (
            self._drag_stream_minimum_interval_seconds
            if is_drag_stream
            else self._minimum_interval_seconds
        )
        with self._lock:
            last_sent_at = self._last_sent_at_by_kind.get(rate_limit_key, -minimum_interval)
            if gesture_phase != "end" and now - last_sent_at < minimum_interval:
                return False
            if gesture_phase == "end":
                self._last_sent_at_by_kind.pop(rate_limit_key, None)
            else:
                self._last_sent_at_by_kind[rate_limit_key] = now
        payload: dict[str, object] = {
            "schema_version": 1,
            "type": "interaction_stimulus",
            "stimulus_kind": kind,
            "position": {"x": x, "y": y},
        }
        if start_position is not None:
            payload["start_position"] = {
                "x": start_position[0],
                "y": start_position[1],
            }
        if duration_ms is not None:
            payload["duration_ms"] = duration_ms
        if is_drag_stream:
            payload["gesture_id"] = gesture_id
            payload["gesture_phase"] = gesture_phase
            payload["gesture_sequence"] = gesture_sequence
            payload["particle_zone"] = particle_zone
        packet = json.dumps(payload, separators=(",", ":")).encode("utf-8")
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
            kind = payload.get("kind") if payload is not None else None
            if not isinstance(kind, str) or kind not in SUPPORTED_STIMULI:
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
            start_position = payload.get("start_position")
            normalized_start: tuple[float, float] | None = None
            if kind == "drag":
                if not isinstance(start_position, dict):
                    self._json(
                        {"status": "rejected", "reason": "invalid_start_position"},
                        HTTPStatus.BAD_REQUEST,
                    )
                    return
                start_x = start_position.get("x")
                start_y = start_position.get("y")
                if not self._normalized_number(start_x) or not self._normalized_number(start_y):
                    self._json(
                        {"status": "rejected", "reason": "invalid_start_position"},
                        HTTPStatus.BAD_REQUEST,
                    )
                    return
                normalized_start = (float(start_x), float(start_y))
            duration_ms = payload.get("duration_ms")
            normalized_duration: float | None = None
            if kind in {"long_press", "drag"}:
                maximum_duration_ms = 60_000 if kind == "drag" else 10_000
                if (
                    not isinstance(duration_ms, (int, float))
                    or isinstance(duration_ms, bool)
                    or not 0 <= float(duration_ms) <= maximum_duration_ms
                ):
                    self._json(
                        {"status": "rejected", "reason": "invalid_duration"},
                        HTTPStatus.BAD_REQUEST,
                    )
                    return
                normalized_duration = float(duration_ms)
            gesture_id: str | None = None
            gesture_phase: str | None = None
            gesture_sequence: int | None = None
            particle_zone: dict[str, object] | None = None
            if kind == "drag":
                raw_gesture_id = payload.get("gesture_id")
                raw_gesture_phase = payload.get("gesture_phase")
                raw_gesture_sequence = payload.get("gesture_sequence")
                has_stream_metadata = any(
                    value is not None
                    for value in (
                        raw_gesture_id,
                        raw_gesture_phase,
                        raw_gesture_sequence,
                    )
                )
                if has_stream_metadata:
                    if (
                        not isinstance(raw_gesture_id, str)
                        or not 1 <= len(raw_gesture_id) <= 64
                        or raw_gesture_phase not in DRAG_STREAM_PHASES
                        or not isinstance(raw_gesture_sequence, int)
                        or isinstance(raw_gesture_sequence, bool)
                        or not 0 <= raw_gesture_sequence <= 1_000_000
                    ):
                        self._json(
                            {"status": "rejected", "reason": "invalid_drag_stream"},
                            HTTPStatus.BAD_REQUEST,
                        )
                        return
                    gesture_id = raw_gesture_id
                    gesture_phase = raw_gesture_phase
                    gesture_sequence = raw_gesture_sequence
                    particle_zone = self._normalized_particle_zone(payload.get("particle_zone"))
                    if particle_zone is None:
                        self._json(
                            {"status": "rejected", "reason": "invalid_particle_zone"},
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
                accepted = stimulus_gateway.send_stimulus(
                    kind,
                    float(x),
                    float(y),
                    start_position=normalized_start,
                    duration_ms=normalized_duration,
                    gesture_id=gesture_id,
                    gesture_phase=gesture_phase,
                    gesture_sequence=gesture_sequence,
                    particle_zone=particle_zone,
                )
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

        @classmethod
        def _normalized_particle_zone(
            cls,
            value: object,
        ) -> dict[str, object] | None:
            if not isinstance(value, dict):
                return None
            center = value.get("center")
            if not isinstance(center, dict):
                return None
            center_x = center.get("x")
            center_y = center.get("y")
            radius_x = value.get("radius_x")
            radius_y = value.get("radius_y")
            if (
                not cls._normalized_number(center_x)
                or not cls._normalized_number(center_y)
                or not isinstance(radius_x, (int, float))
                or isinstance(radius_x, bool)
                or not isinstance(radius_y, (int, float))
                or isinstance(radius_y, bool)
                or not 0 < float(radius_x) <= 1
                or not 0 < float(radius_y) <= 1
            ):
                return None
            return {
                "center": {"x": float(center_x), "y": float(center_y)},
                "radius_x": float(radius_x),
                "radius_y": float(radius_y),
            }

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
            # The visualizer is iterated locally; never reuse an older script or
            # stylesheet after a page reload.
            self.send_header("Cache-Control", "no-store")
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
