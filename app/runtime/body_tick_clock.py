from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from collections.abc import Callable


@dataclass(frozen=True, slots=True)
class BodyTick:
    sequence: int
    timestamp_ms: int
    dt_seconds: float


class BodyTickClock:
    """Body Tickの時刻・dt・sequence解決だけを担当する。"""

    def __init__(
        self,
        *,
        tick_hz: float = 30.0,
        monotonic_clock: Callable[[], float] = monotonic,
    ) -> None:
        if isinstance(tick_hz, bool) or not isinstance(tick_hz, (int, float)):
            raise TypeError("tick_hz must be a number")
        normalized = float(tick_hz)
        if not 10.0 <= normalized <= 120.0:
            raise ValueError("tick_hz must be between 10 and 120")
        self._tick_hz = normalized
        self._monotonic = monotonic_clock
        self._last_timestamp_ms: int | None = None
        self._sequence = 0

    @property
    def tick_hz(self) -> float:
        return self._tick_hz

    @property
    def tick_interval_seconds(self) -> float:
        return 1.0 / self._tick_hz

    def next(
        self,
        *,
        timestamp_ms: int | None = None,
        dt_seconds: float | None = None,
    ) -> BodyTick:
        now_ms = (
            int(self._monotonic() * 1000)
            if timestamp_ms is None
            else self._timestamp(timestamp_ms)
        )
        if dt_seconds is None:
            if self._last_timestamp_ms is None:
                dt = self.tick_interval_seconds
            else:
                dt = (now_ms - self._last_timestamp_ms) / 1000.0
        else:
            if isinstance(dt_seconds, bool) or not isinstance(dt_seconds, (int, float)):
                raise TypeError("dt_seconds must be a number")
            dt = float(dt_seconds)
        self._last_timestamp_ms = now_ms
        self._sequence += 1
        return BodyTick(
            sequence=self._sequence,
            timestamp_ms=now_ms,
            dt_seconds=max(1.0 / 240.0, min(0.1, dt)),
        )

    @staticmethod
    def _timestamp(value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("timestamp_ms must be an integer")
        if value < 0:
            raise ValueError("timestamp_ms must not be negative")
        return value
