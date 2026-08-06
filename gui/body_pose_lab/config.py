from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_FALSE_VALUES = {"0", "false", "off", "no"}
_TRUE_VALUES = {"1", "true", "on", "yes"}


@dataclass(frozen=True, slots=True)
class BodyPoseLabConfig:
    """Body Pose Labの起動設定。"""

    host: str = "127.0.0.1"
    port: int = 8768
    tick_hz: float = 30.0
    random_seed: int | None = 23
    local_simulation: bool = True
    maximum_subscribers: int = 32
    maximum_json_bytes: int = 512 * 1024

    def __post_init__(self) -> None:
        host = self.host.strip()
        if not host or len(host) > 255:
            raise ValueError("host must contain 1 to 255 characters")
        if isinstance(self.port, bool) or not isinstance(self.port, int):
            raise TypeError("port must be an integer")
        if not 0 <= self.port <= 65_535:
            raise ValueError("port must be between 0 and 65535")
        if isinstance(self.tick_hz, bool) or not isinstance(
            self.tick_hz, (int, float)
        ):
            raise TypeError("tick_hz must be a number")
        tick_hz = float(self.tick_hz)
        if not 10.0 <= tick_hz <= 120.0:
            raise ValueError("tick_hz must be between 10 and 120")
        if self.random_seed is not None and (
            isinstance(self.random_seed, bool)
            or not isinstance(self.random_seed, int)
        ):
            raise TypeError("random_seed must be an integer")
        if not 1 <= self.maximum_subscribers <= 256:
            raise ValueError("maximum_subscribers must be between 1 and 256")
        if not 1024 <= self.maximum_json_bytes <= 4 * 1024 * 1024:
            raise ValueError("maximum_json_bytes is outside the supported range")
        object.__setattr__(self, "host", host)
        object.__setattr__(self, "tick_hz", tick_hz)

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> BodyPoseLabConfig:
        values = environ or os.environ
        return cls(
            host=values.get("YURA_BODY_POSE_LAB_HOST", "127.0.0.1"),
            port=int(
                values.get("YURA_BODY_POSE_LAB_PORT")
                or values.get("PORT")
                or "8768"
            ),
            tick_hz=float(values.get("YURA_BODY_POSE_LAB_TICK_HZ", "30")),
            random_seed=cls._optional_integer(
                values.get("YURA_BODY_POSE_LAB_RANDOM_SEED", "23")
            ),
            local_simulation=cls._boolean(
                values.get("YURA_BODY_POSE_LAB_LOCAL_SIMULATION"),
                default=True,
            ),
            maximum_subscribers=int(
                values.get("YURA_BODY_POSE_LAB_MAX_SUBSCRIBERS", "32")
            ),
            maximum_json_bytes=int(
                values.get("YURA_BODY_POSE_LAB_MAX_JSON_BYTES", str(512 * 1024))
            ),
        )

    @staticmethod
    def default_web_root() -> Path:
        return Path(__file__).resolve().parents[1] / "yura-body-pose-lab" / "web"

    @staticmethod
    def _optional_integer(value: str | None) -> int | None:
        if value is None or not value.strip():
            return None
        return int(value)

    @staticmethod
    def _boolean(value: str | None, *, default: bool) -> bool:
        if value is None:
            return default
        normalized = value.strip().lower()
        if normalized in _TRUE_VALUES:
            return True
        if normalized in _FALSE_VALUES:
            return False
        raise ValueError(f"invalid boolean environment value: {value!r}")
