from __future__ import annotations

import json
import mimetypes
import os
import sys
import threading
import time
from dataclasses import fields
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

LAB_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = LAB_ROOT.parents[1]
for import_root in (LAB_ROOT, PROJECT_ROOT):
    import_root_text = str(import_root)
    if import_root_text not in sys.path:
        sys.path.insert(0, import_root_text)

from app.domain.body_kinematics import GenerativeBodyPoseFrame  # noqa: E402
from app.domain.body_motion import BodyMotionPlan, BodyMotionRequest  # noqa: E402
from app.domain.body_pose_frame import (  # noqa: E402
    BodyAttentionCandidate,
    BodyInnerMotionState,
)
from app.runtime.generative_body_motion_controller import (  # noqa: E402
    GenerativeBodyMotionController,
)

WEB_ROOT = LAB_ROOT / "web"
MAX_BODY_BYTES = 65_536


class BodyPoseLabHub:
    def __init__(self, *, tick_hz: float = 30.0) -> None:
        self._tick_hz = tick_hz
        self._controller = GenerativeBodyMotionController(
            tick_hz=tick_hz,
            seed=514,
        )
        self._condition = threading.Condition()
        self._running = False
        self._thread: threading.Thread | None = None
        self._latest = self._controller.tick(
            timestamp_ms=int(time.monotonic() * 1000)
        )
        self._controller.set_attention_candidates(
            (
                BodyAttentionCandidate(
                    "viewer",
                    0.0,
                    0.0,
                    salience=0.72,
                    novelty=0.05,
                    relevance=1.0,
                    stability=0.94,
                ),
                BodyAttentionCandidate(
                    "left_light",
                    -0.78,
                    -0.24,
                    salience=0.46,
                    novelty=0.82,
                    relevance=0.26,
                    stability=0.42,
                ),
                BodyAttentionCandidate(
                    "right_sound",
                    0.82,
                    0.1,
                    salience=0.58,
                    novelty=0.48,
                    threat=0.34,
                    relevance=0.34,
                    stability=0.32,
                ),
            )
        )

    @property
    def tick_hz(self) -> float:
        return self._tick_hz

    def start(self) -> None:
        with self._condition:
            if self._running:
                return
            self._running = True
        self._thread = threading.Thread(
            target=self._run,
            name="BodyPoseLabController",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        with self._condition:
            self._running = False
            self._condition.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def snapshot(self) -> GenerativeBodyPoseFrame:
        with self._condition:
            return self._latest

    def wait_for_frame(
        self,
        after_sequence: int,
        *,
        timeout: float = 2.0,
    ) -> GenerativeBodyPoseFrame:
        with self._condition:
            self._condition.wait_for(
                lambda: self._latest.sequence > after_sequence or not self._running,
                timeout=timeout,
            )
            return self._latest

    def update_inner_state(self, payload: dict[str, object]) -> BodyInnerMotionState:
        allowed = {field.name for field in fields(BodyInnerMotionState)}
        changes: dict[str, float] = {}
        for key, value in payload.items():
            if key not in allowed:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{key} must be a number")
            changes[key] = float(value)
        with self._condition:
            self._controller.update_inner_state(**changes)
            return self._controller.inner_state

    def update_candidates(self, payload: object) -> tuple[BodyAttentionCandidate, ...]:
        if not isinstance(payload, list):
            raise ValueError("candidates must be an array")
        candidates: list[BodyAttentionCandidate] = []
        for item in payload:
            if not isinstance(item, dict):
                raise ValueError("candidate entries must be objects")
            candidates.append(
                BodyAttentionCandidate(
                    candidate_id=str(item.get("candidate_id", "")),
                    x=float(item.get("x", 0.0)),
                    y=float(item.get("y", 0.0)),
                    salience=float(item.get("salience", 0.5)),
                    novelty=float(item.get("novelty", 0.0)),
                    threat=float(item.get("threat", 0.0)),
                    relevance=float(item.get("relevance", 0.5)),
                    stability=float(item.get("stability", 0.7)),
                )
            )
        with self._condition:
            self._controller.set_attention_candidates(candidates)
        return tuple(candidates)

    def submit_motion(self, payload: object) -> BodyMotionPlan:
        request = BodyMotionRequest.from_payload(payload)
        with self._condition:
            return self._controller.submit_motion(request)

    def cancel_motion(self, plan_id: str) -> bool:
        with self._condition:
            return self._controller.cancel_motion(plan_id)

    def clear_motions(self, *, release_holds: bool) -> None:
        with self._condition:
            self._controller.clear_motions(release_holds=release_holds)

    def motion_status(self) -> dict[str, object]:
        with self._condition:
            return {
                "active_motion_ids": list(self._controller.active_motion_ids),
                "held_targets": list(self._controller.held_targets),
            }

    def _run(self) -> None:
        interval = 1.0 / self._tick_hz
        next_tick = time.monotonic()
        while True:
            with self._condition:
                if not self._running:
                    return
            now = time.monotonic()
            if now < next_tick:
                time.sleep(min(interval, next_tick - now))
                continue
            with self._condition:
                frame = self._controller.tick(
                    timestamp_ms=int(now * 1000),
                    dt_seconds=interval,
                )
                self._latest = frame
                self._condition.notify_all()
            next_tick += interval
            if next_tick < now - interval:
                next_tick = now + interval


HUB = BodyPoseLabHub(
    tick_hz=float(os.getenv("YURA_BODY_POSE_LAB_TICK_HZ", "30"))
)


class BodyPoseLabHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            self._json_response(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "tick_hz": HUB.tick_hz,
                    "sequence": HUB.snapshot().sequence,
                    **HUB.motion_status(),
                },
            )
            return
        if path == "/api/snapshot":
            self._json_response(HTTPStatus.OK, HUB.snapshot().as_payload())
            return
        if path == "/api/motions":
            self._json_response(HTTPStatus.OK, HUB.motion_status())
            return
        if path == "/api/frames":
            self._stream_frames()
            return
        if path == "/":
            self._serve_static("index.html")
            return
        if path.startswith("/"):
            self._serve_static(path[1:])
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            payload = self._read_json()
            if path == "/api/state":
                if not isinstance(payload, dict):
                    raise ValueError("state must be an object")
                state = HUB.update_inner_state(payload)
                self._json_response(
                    HTTPStatus.OK,
                    {"status": "updated", "inner_state": state.as_payload()},
                )
                return
            if path == "/api/candidates":
                candidates = HUB.update_candidates(payload)
                self._json_response(
                    HTTPStatus.OK,
                    {
                        "status": "updated",
                        "candidates": [candidate.as_payload() for candidate in candidates],
                    },
                )
                return
            if path == "/api/motion":
                plan = HUB.submit_motion(payload)
                self._json_response(
                    HTTPStatus.ACCEPTED,
                    {"status": "accepted", "plan": plan.as_payload()},
                )
                return
            if path == "/api/motion/cancel":
                if not isinstance(payload, dict):
                    raise ValueError("cancel request must be an object")
                plan_id = str(payload.get("plan_id", "")).strip()
                if not plan_id:
                    raise ValueError("plan_id is required")
                cancelled = HUB.cancel_motion(plan_id)
                self._json_response(
                    HTTPStatus.OK,
                    {"status": "cancelled" if cancelled else "not_found"},
                )
                return
            if path == "/api/motion/clear":
                if not isinstance(payload, dict):
                    raise ValueError("clear request must be an object")
                HUB.clear_motions(
                    release_holds=bool(payload.get("release_holds", False))
                )
                self._json_response(
                    HTTPStatus.OK,
                    {"status": "cleared", **HUB.motion_status()},
                )
                return
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            self._json_response(
                HTTPStatus.BAD_REQUEST,
                {"status": "error", "message": str(error)},
            )
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: object) -> None:
        print(f"[body-pose-lab] {self.address_string()} {format % args}")

    def _stream_frames(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        sequence = 0
        try:
            while True:
                frame = HUB.wait_for_frame(sequence, timeout=1.5)
                if frame.sequence <= sequence:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                    continue
                sequence = frame.sequence
                data = json.dumps(
                    frame.as_payload(),
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
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

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
        error = sys.exc_info()[1]
        if isinstance(
            error,
            (BrokenPipeError, ConnectionResetError, ConnectionAbortedError),
        ):
            return
        super().handle_error(request, client_address)


def main() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    HUB.start()
    server = QuietDisconnectHTTPServer((host, port), BodyPoseLabHandler)
    print(f"Body Pose Lab listening on http://{host}:{port}")
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        HUB.stop()


if __name__ == "__main__":
    main()
