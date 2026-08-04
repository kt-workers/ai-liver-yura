from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import threading
from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

WEB_ROOT = Path(__file__).parent / "web"
MAX_BODY_BYTES = 8_192
MAX_HISTORY_ITEMS = 50
NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
SUPPORTED_ACTIONS = frozenset({"expression", "gesture", "gaze"})
SUPPORTED_GAZE_BEHAVIORS = frozenset({"maintain", "glance", "wander"})


class AvatarStateHub:
    """直近のAvatar Actionとブラウザ配信用状態を保持する。"""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._sequence = 0
        self._state: dict[str, Any] = {
            "schema_version": 1,
            "sequence": 0,
            "status": "waiting",
            "expression": "neutral",
            "gesture": None,
            "gaze": {
                "target": "neutral",
                "behavior": "maintain",
                "intensity": 1.0,
            },
            "latest_action": None,
            "received_at": None,
            "history": [],
        }
        self._history: deque[dict[str, Any]] = deque(maxlen=MAX_HISTORY_ITEMS)

    def publish(self, action: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        with self._condition:
            self._sequence += 1
            action_type = action["action"]
            if action_type == "expression":
                self._state["expression"] = action["name"]
            elif action_type == "gesture":
                self._state["gesture"] = action["name"]
            elif action_type == "gaze":
                self._state["gaze"] = {
                    "target": action["target"],
                    "behavior": action["behavior"],
                    "intensity": action["intensity"],
                }
            history_item = {
                "sequence": self._sequence,
                "received_at": now,
                "action": deepcopy(action),
            }
            self._history.appendleft(history_item)
            self._state.update(
                {
                    "sequence": self._sequence,
                    "status": "active",
                    "latest_action": deepcopy(action),
                    "received_at": now,
                    "history": list(self._history),
                }
            )
            snapshot = deepcopy(self._state)
            self._condition.notify_all()
            return snapshot

    def snapshot(self) -> dict[str, Any]:
        with self._condition:
            return deepcopy(self._state)

    def wait_next(self, sequence: int, timeout: float) -> dict[str, Any]:
        with self._condition:
            self._condition.wait_for(
                lambda: self._sequence > sequence,
                timeout=timeout,
            )
            return deepcopy(self._state)


def validate_avatar_action(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    if payload.get("schema_version") != 1:
        raise ValueError("schema_version must be 1")
    if payload.get("type") != "avatar.action":
        raise ValueError("type must be avatar.action")
    action = payload.get("action")
    if action not in SUPPORTED_ACTIONS:
        raise ValueError("unsupported action")

    intensity = _number_between(payload.get("intensity", 1.0), 0.0, 1.0)
    if action in {"expression", "gesture"}:
        name = _validated_name(payload.get("name"), "name")
        return {
            "schema_version": 1,
            "type": "avatar.action",
            "action": action,
            "name": name,
            "intensity": intensity,
        }

    target = _validated_name(payload.get("target"), "target")
    behavior = payload.get("behavior", "maintain")
    if behavior not in SUPPORTED_GAZE_BEHAVIORS:
        raise ValueError("unsupported gaze behavior")
    return {
        "schema_version": 1,
        "type": "avatar.action",
        "action": "gaze",
        "target": target,
        "behavior": behavior,
        "intensity": intensity,
    }


def handler_for(hub: AvatarStateHub) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "YuraAvatarRuntimeLab/1.0"

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(HTTPStatus.NO_CONTENT)
            self._cors_headers()
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/health":
                self._json({"status": "ok", "service": "avatar-runtime-lab"})
                return
            if path == "/api/avatar/state":
                self._json(hub.snapshot())
                return
            if path == "/api/avatar/events":
                self._events()
                return
            self._static(path)

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path != "/api/avatar/actions":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                payload = self._read_json()
                action = validate_avatar_action(payload)
            except ValueError as error:
                self._json(
                    {"status": "rejected", "reason": str(error)},
                    HTTPStatus.BAD_REQUEST,
                )
                return
            snapshot = hub.publish(action)
            self._json(
                {
                    "status": "accepted",
                    "sequence": snapshot["sequence"],
                },
                HTTPStatus.ACCEPTED,
            )

        def _events(self) -> None:
            self.send_response(HTTPStatus.OK)
            self._cors_headers()
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            sequence = -1
            try:
                while True:
                    state = hub.wait_next(sequence, timeout=15.0)
                    sequence = int(state["sequence"])
                    data = json.dumps(
                        state,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    self.wfile.write(f"event: avatar-state\ndata: {data}\n\n".encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return

        def _read_json(self) -> object:
            raw_length = self.headers.get("Content-Length", "")
            try:
                length = int(raw_length)
            except ValueError as error:
                raise ValueError("invalid Content-Length") from error
            if length <= 0 or length > MAX_BODY_BYTES:
                raise ValueError("invalid request body size")
            body = self.rfile.read(length)
            try:
                return json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError("invalid JSON") from error

        def _json(
            self,
            payload: object,
            status: HTTPStatus = HTTPStatus.OK,
        ) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self._cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _static(self, path: str) -> None:
            requested = "index.html" if path in {"", "/"} else path.lstrip("/")
            candidate = (WEB_ROOT / requested).resolve()
            try:
                candidate.relative_to(WEB_ROOT.resolve())
            except ValueError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if not candidate.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            body = candidate.read_bytes()
            content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _cors_headers(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")

        def log_message(self, format: str, *args: object) -> None:
            print(f"[avatar-runtime-lab] {self.address_string()} {format % args}")

    return Handler


def _validated_name(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not NAME_PATTERN.fullmatch(value):
        raise ValueError(f"{field_name} must match {NAME_PATTERN.pattern}")
    return value


def _number_between(value: object, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("intensity must be a number")
    normalized = float(value)
    if not minimum <= normalized <= maximum:
        raise ValueError("intensity must be between 0.0 and 1.0")
    return normalized


def main() -> None:
    parser = argparse.ArgumentParser(description="Yura Avatar Runtime Web MVP")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("PORT", "8780")),
    )
    args = parser.parse_args()
    hub = AvatarStateHub()
    server = ThreadingHTTPServer((args.host, args.port), handler_for(hub))
    print(f"avatar runtime lab listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
