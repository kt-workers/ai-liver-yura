from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from app.domain.body_value_validation import finite_number

_FALSE_VALUES = {"0", "false", "off", "no"}
_TRUE_VALUES = {"1", "true", "on", "yes"}


@dataclass(frozen=True, slots=True)
class BodyRuntimeSettings:
    """環境変数から解決したBody Runtimeの型付きComposition設定。"""

    enabled: bool = False
    tick_hz: float = 30.0
    pose_output_url: str | None = None
    pose_timeout_seconds: float = 1.0
    pose_source_name: str = "yura-core-state-driven-body"
    random_seed: int | None = None

    def __post_init__(self) -> None:
        tick_hz = finite_number(self.tick_hz, "tick_hz")
        if not 10.0 <= tick_hz <= 120.0:
            raise ValueError("tick_hz must be between 10 and 120")
        timeout = finite_number(self.pose_timeout_seconds, "pose_timeout_seconds")
        if not 0.05 <= timeout <= 30.0:
            raise ValueError("pose_timeout_seconds must be between 0.05 and 30")
        output_url = self.pose_output_url
        if output_url is not None:
            if not isinstance(output_url, str):
                raise TypeError("pose_output_url must be a string")
            output_url = output_url.strip() or None
        if not isinstance(self.pose_source_name, str):
            raise TypeError("pose_source_name must be a string")
        source_name = self.pose_source_name.strip()
        if not source_name or len(source_name) > 80:
            raise ValueError("pose_source_name must contain 1 to 80 characters")
        if self.random_seed is not None and (
            isinstance(self.random_seed, bool)
            or not isinstance(self.random_seed, int)
        ):
            raise TypeError("random_seed must be an integer")
        object.__setattr__(self, "tick_hz", tick_hz)
        object.__setattr__(self, "pose_timeout_seconds", timeout)
        object.__setattr__(self, "pose_output_url", output_url)
        object.__setattr__(self, "pose_source_name", source_name)

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        default_enabled: bool = False,
    ) -> BodyRuntimeSettings:
        values = environ or os.environ
        return cls(
            enabled=cls._boolean(
                values.get("YURA_BODY_RUNTIME_ENABLED"),
                default=default_enabled,
            ),
            tick_hz=float(values.get("YURA_BODY_TICK_HZ", "30")),
            pose_output_url=values.get("YURA_BODY_POSE_OUTPUT_URL"),
            pose_timeout_seconds=float(
                values.get("YURA_BODY_POSE_TIMEOUT_SECONDS", "1.0")
            ),
            pose_source_name=values.get(
                "YURA_BODY_POSE_SOURCE_NAME",
                "yura-core-state-driven-body",
            ),
            random_seed=(
                int(values["YURA_BODY_RANDOM_SEED"])
                if values.get("YURA_BODY_RANDOM_SEED", "").strip()
                else None
            ),
        )

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
