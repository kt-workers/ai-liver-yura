from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from threading import Thread
from time import monotonic, sleep
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from gui.body_pose_lab.composition import (
    BodyPoseLabComponents,
    BodyPoseLabComposition,
)
from gui.body_pose_lab.config import BodyPoseLabConfig


@dataclass(slots=True)
class BodyPoseLabHttpHarness:
    """実Socketを使うBody Pose Lab統合テストのlifecycleと通信を担当する。"""

    components: BodyPoseLabComponents
    server_thread: Thread

    @classmethod
    def start(
        cls,
        *,
        local_simulation: bool = False,
        tick_hz: float = 30.0,
    ) -> BodyPoseLabHttpHarness:
        components = BodyPoseLabComposition.create(
            BodyPoseLabConfig(
                host="127.0.0.1",
                port=0,
                tick_hz=tick_hz,
                random_seed=31,
                local_simulation=local_simulation,
            )
        )
        if local_simulation:
            components.tick_loop.start()
        server_thread = Thread(
            target=components.http_server.serve_forever,
            name="body-pose-lab-http-test",
            daemon=True,
        )
        server_thread.start()
        harness = cls(components=components, server_thread=server_thread)
        harness.wait_until(
            lambda: harness.json_request("GET", "/health")[0] == 200,
            timeout_seconds=2.0,
        )
        return harness

    @property
    def base_url(self) -> str:
        host, port = self.components.http_server.address
        return f"http://{host}:{port}"

    def close(self) -> None:
        self.components.tick_loop.stop()
        self.components.http_server.shutdown()
        self.server_thread.join(timeout=2.0)
        if self.server_thread.is_alive():
            raise AssertionError("Body Pose Lab HTTP server did not stop")

    def __enter__(self) -> BodyPoseLabHttpHarness:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def json_request(
        self,
        method: str,
        path: str,
        payload: object | None = None,
    ) -> tuple[int, dict[str, object]]:
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=2.0) as response:
                return int(response.status), json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            return int(error.code), json.loads(error.read().decode("utf-8"))

    def bytes_request(self, path: str) -> tuple[int, str, bytes]:
        request = Request(
            f"{self.base_url}{path}",
            headers={"Accept": "*/*"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=2.0) as response:
                return (
                    int(response.status),
                    str(response.headers.get("Content-Type") or ""),
                    response.read(),
                )
        except HTTPError as error:
            return (
                int(error.code),
                str(error.headers.get("Content-Type") or ""),
                error.read(),
            )

    def first_sse_event(self) -> tuple[str, dict[str, object]]:
        request = Request(
            f"{self.base_url}/api/frames",
            headers={"Accept": "text/event-stream"},
            method="GET",
        )
        with urlopen(request, timeout=2.0) as response:
            event_name = "message"
            data_lines: list[str] = []
            while True:
                raw_line = response.readline()
                if not raw_line:
                    raise AssertionError("SSE stream ended before first event")
                line = raw_line.decode("utf-8").rstrip("\r\n")
                if not line:
                    if data_lines:
                        return event_name, json.loads("\n".join(data_lines))
                    continue
                if line.startswith(":"):
                    continue
                if line.startswith("event:"):
                    event_name = line.removeprefix("event:").strip()
                elif line.startswith("data:"):
                    data_lines.append(line.removeprefix("data:").strip())

    @staticmethod
    def wait_until(
        predicate: Callable[[], bool],
        *,
        timeout_seconds: float = 2.0,
        interval_seconds: float = 0.01,
    ) -> None:
        deadline = monotonic() + timeout_seconds
        while monotonic() < deadline:
            if predicate():
                return
            sleep(interval_seconds)
        raise AssertionError("condition was not satisfied before timeout")
