from __future__ import annotations

from collections.abc import Callable
from time import monotonic

from app.domain.body_expression_request import BodyExpressionRequest


class TimedBodyExpressionRequestStore:
    """一時Body表現要求の保持期限だけを管理する。"""

    def __init__(
        self,
        *,
        default_duration_ms: int = 900,
        monotonic_clock: Callable[[], float] = monotonic,
    ) -> None:
        if isinstance(default_duration_ms, bool) or not isinstance(
            default_duration_ms,
            int,
        ):
            raise TypeError("default_duration_ms must be an integer")
        if not 100 <= default_duration_ms <= 120_000:
            raise ValueError("default_duration_ms must be between 100 and 120000")
        self._default_duration_ms = default_duration_ms
        self._monotonic = monotonic_clock
        self._request: BodyExpressionRequest | None = None
        self._expires_at: float | None = None

    @property
    def pending_count(self) -> int:
        return 1 if self.current() is not None else 0

    def set(self, request: BodyExpressionRequest) -> None:
        if not isinstance(request, BodyExpressionRequest):
            raise TypeError("request must be BodyExpressionRequest")
        duration_ms = request.duration_hint_ms or self._default_duration_ms
        self._request = request
        self._expires_at = self._monotonic() + duration_ms / 1000.0

    def clear(self) -> None:
        self._request = None
        self._expires_at = None

    def current(self) -> BodyExpressionRequest | None:
        if self._request is None:
            return None
        expires_at = self._expires_at
        if expires_at is not None and self._monotonic() >= expires_at:
            self.clear()
            return None
        return self._request
