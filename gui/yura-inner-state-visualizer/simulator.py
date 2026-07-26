from __future__ import annotations

import argparse
import json
import select
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.domain.drives import DriveState  # noqa: E402
from app.domain.emotions import EmotionState  # noqa: E402
from app.domain.events import AgentEvent, AgentEventType  # noqa: E402
from app.runtime.drive_state_updater import DriveStateUpdater  # noqa: E402
from app.runtime.emotion_appraiser import EmotionAppraiser  # noqa: E402
from app.runtime.emotion_state_updater import EmotionStateUpdater  # noqa: E402

SUPPORTED_STIMULI = frozenset({"tap", "double_tap", "long_press", "drag"})
REACTION_ACTIVITY_SECONDS = 3.0


class InteractiveStateSimulator:
    """Coreと同じ評価器を使って画面刺激への内部状態変化を模擬する。"""

    def __init__(self, *, now: float | None = None) -> None:
        self.emotion = EmotionState()
        self.drive = DriveState()
        self._emotion_appraiser = EmotionAppraiser()
        self._emotion_updater = EmotionStateUpdater()
        self._drive_updater = DriveStateUpdater()
        self._last_updated_at = time.monotonic() if now is None else now
        self._reaction_until = 0.0
        self._last_stimulus_kind: str | None = None

    def apply_stimulus(self, payload: object, *, now: float | None = None) -> bool:
        if not isinstance(payload, dict):
            return False
        if (
            payload.get("schema_version") != 1
            or payload.get("type") != "interaction_stimulus"
        ):
            return False
        kind = payload.get("stimulus_kind")
        if not isinstance(kind, str) or kind not in SUPPORTED_STIMULI:
            return False
        if not self._valid_position(payload.get("position")):
            return False
        current_time = time.monotonic() if now is None else now
        self.advance(current_time)
        event = AgentEvent(
            event_type=AgentEventType.USER_INTERACTION,
            payload=dict(payload),
        )
        appraisal = self._emotion_appraiser.appraise(event)
        self.emotion = self._emotion_updater.apply(self.emotion, appraisal)
        self.drive = self._drive_updater.update_by_event(self.drive, event)
        self._last_stimulus_kind = kind
        self._reaction_until = current_time + REACTION_ACTIVITY_SECONDS
        return True

    def advance(self, now: float | None = None) -> None:
        current_time = time.monotonic() if now is None else now
        elapsed = max(0.0, current_time - self._last_updated_at)
        self._last_updated_at = current_time
        self.emotion = self._emotion_updater.decay(
            self.emotion,
            elapsed_seconds=elapsed,
        )

    def snapshot(
        self,
        *,
        now: float | None = None,
        observed_at: datetime | None = None,
    ) -> dict[str, Any]:
        current_time = time.monotonic() if now is None else now
        self.advance(current_time)
        reacting = current_time < self._reaction_until
        return {
            "schema_version": 1,
            "observed_at": (
                observed_at or datetime.now(timezone.utc)
            ).isoformat(),
            "emotion": {
                "mood": self.emotion.mood.value,
                "arousal": self.emotion.arousal,
                "valence": self.emotion.valence,
                "talkativeness": self.emotion.talkativeness,
                "reactive": self.emotion.reactive.as_dict(),
            },
            "drive": {
                "curiosity": self.drive.curiosity,
                "engagement": self.drive.engagement,
                "boredom": self.drive.boredom,
                "energy": self.drive.energy,
            },
            "activity": {
                "type": (
                    f"stimulus_{self._last_stimulus_kind}"
                    if reacting and self._last_stimulus_kind
                    else "idle_observation"
                ),
                "active": reacting,
                "pending_count": 0,
            },
            "attention": {"engaged": reacting},
            "stream": {"status": "idle"},
        }

    @staticmethod
    def _valid_position(value: object) -> bool:
        if not isinstance(value, dict):
            return False
        x = value.get("x")
        y = value.get("y")
        return (
            isinstance(x, (int, float))
            and not isinstance(x, bool)
            and isinstance(y, (int, float))
            and not isinstance(y, bool)
            and 0.0 <= float(x) <= 1.0
            and 0.0 <= float(y) <= 1.0
        )


def _receive_stimuli(
    receiver: socket.socket,
    simulator: InteractiveStateSimulator,
) -> list[str]:
    accepted: list[str] = []
    while True:
        try:
            packet, _ = receiver.recvfrom(65535)
        except BlockingIOError:
            return accepted
        try:
            payload = json.loads(packet.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if simulator.apply_stimulus(payload):
            accepted.append(str(payload["stimulus_kind"]))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Simulate Yura state and reactions to visualizer gestures"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--interaction-host", default="127.0.0.1")
    parser.add_argument("--interaction-port", type=int, default=8771)
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("--interval must be greater than zero")

    simulator = InteractiveStateSimulator()
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender,
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver,
    ):
        receiver.bind((args.interaction_host, args.interaction_port))
        receiver.setblocking(False)
        print(f"Telemetry UDP: {args.host}:{args.port} every {args.interval:.2f}s")
        print(
            "Interaction UDP: "
            f"{args.interaction_host}:{args.interaction_port} "
            "(tap / double_tap / long_press / drag)"
        )
        next_publish_at = 0.0
        try:
            while True:
                timeout = max(0.0, next_publish_at - time.monotonic())
                select.select([receiver], [], [], timeout)
                received_kinds = _receive_stimuli(receiver, simulator)
                for kind in received_kinds:
                    print(f"Received stimulus: {kind}")
                now = time.monotonic()
                if not received_kinds and now < next_publish_at:
                    continue
                state = simulator.snapshot()
                sender.sendto(
                    json.dumps(state, separators=(",", ":")).encode(),
                    (args.host, args.port),
                )
                next_publish_at = now + args.interval
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
