"""Null dependency health provider for an intentionally absent integration."""

from collections.abc import Callable
from datetime import datetime, timezone

from app.integrations.streaming import (
    DependencyKind,
    DependencyState,
    StreamingDependencyHealth,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class NullDependencyHealthProvider:
    def __init__(
        self,
        kind: DependencyKind,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._kind = kind
        self._clock = clock

    @property
    def kind(self) -> DependencyKind:
        return self._kind

    def get_health(self) -> StreamingDependencyHealth:
        return StreamingDependencyHealth(
            kind=self.kind,
            state=DependencyState.DISCONNECTED,
            healthy=False,
            available=False,
            checked_at=self._clock(),
            message=f"{self.kind.value}_not_connected",
        )
