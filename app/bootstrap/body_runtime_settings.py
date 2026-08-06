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
    expression_queue_limit: int = 32
    max_expressions_per_tick: int = 4
    autonomous_interval_ms: int = 2400
    baseline_refresh_ms: int = 30_000

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

        self._validate_integer_range("expression_queue_limit", 1, 1024)
        self._validate_integer_range("max_expressions_per_tick", 1, 32)
        self._validate_integer_range("autonomous_interval_ms", 250, 120_000)
        self._validate_integer_range("baseline_refresh_ms", 1000, 120_000)

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
            random_seed=cls._optional_integer(
                values.get("YURA_BODY_RANDOM_SEED")
            ),
            expression_queue_limit=int(
                values.get("YURA_BODY_EXPRESSION_QUEUE_LIMIT", "32")
            ),
            max_expressions_per_tick=int(
                values.get("YURA_BODY_MAX_EXPRESSIONS_PER_TICK", "4")
            ),
            autonomous_interval_ms=int(
                values.get("YURA_BODY_AUTONOMOUS_INTERVAL_MS", "2400")
            ),
            baseline_refresh_ms=int(
                values.get("YURA_BODY_BASELINE_REFRESH_MS", "30000")
            ),
        )

    def _validate_integer_range(
        self,
        field_name: str,
        minimum: int,
        maximum: int,
    ) -> None:
        value = getattr(self, field_name)
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{field_name} must be an integer")
        if not minimum <= value <= maximum:
            raise ValueError(
                f"{field_name} must be between {minimum} and {maximum}"
            )

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
