from __future__ import annotations

import importlib.util
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BASE_DIR = Path(__file__).resolve().parent
server_module = _load_module("yura_inner_state_server", BASE_DIR / "server.py")
simulator_module = _load_module("yura_inner_state_simulator", BASE_DIR / "simulator.py")


class DirectStimulusGateway:
    """Render内のデモ状態へ、検証済み画面刺激を直接渡す。"""

    def __init__(self, simulator: Any, *, minimum_interval_seconds: float = 0.75) -> None:
        self._simulator = simulator
        self._minimum_interval_seconds = minimum_interval_seconds
        self._lock = threading.Lock()
        self._last_sent_at_by_kind: dict[str, float] = {}

    def send_stimulus(
        self,
        kind: str,
        x: float,
        y: float,
        *,
        start_position: tuple[float, float] | None = None,
        duration_ms: float | None = None,
    ) -> bool:
        now = time.monotonic()
        with self._lock:
            last_sent_at = self._last_sent_at_by_kind.get(
                kind,
                -self._minimum_interval_seconds,
            )
            if now - last_sent_at < self._minimum_interval_seconds:
                return False
            self._last_sent_at_by_kind[kind] = now

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
        return bool(self._simulator.apply_stimulus(payload, now=now))


class DemoStatePublisher(threading.Thread):
    """Core未接続のRender環境でも画面を確認できる状態を定期配信する。"""

    def __init__(self, hub: Any, simulator: Any, *, interval_seconds: float = 1.0) -> None:
        super().__init__(name="YuraRenderDemoState", daemon=True)
        self._hub = hub
        self._simulator = simulator
        self._interval_seconds = max(0.1, interval_seconds)

    def run(self) -> None:
        while True:
            self._hub.publish(
                self._simulator.snapshot(observed_at=datetime.now(timezone.utc))
            )
            time.sleep(self._interval_seconds)


def main() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "10000"))
    interval = float(os.getenv("YURA_DEMO_INTERVAL_SECONDS", "1.0"))

    hub = server_module.StateHub()
    simulator = simulator_module.InteractiveStateSimulator()
    gateway = DirectStimulusGateway(simulator)
    DemoStatePublisher(hub, simulator, interval_seconds=interval).start()

    http_server = server_module.ThreadingHTTPServer(
        (host, port),
        server_module.handler_for(hub, gateway),
    )
    print(f"Yura inner state visualizer: http://{host}:{port}")
    print("Mode: Render demo (HTTP/SSE + in-process state simulation)")
    try:
        http_server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        http_server.server_close()


if __name__ == "__main__":
    main()
