"""Fault-isolating aggregate for TTS and Avatar health providers."""

from collections.abc import Callable, Iterable
from datetime import datetime, timezone

from app.integrations.streaming import (
    DependencyKind,
    DependencyState,
    StreamingDependencyHealth,
)
from subsystems.streaming.adapters.dependency_health.null_health import (
    NullDependencyHealthProvider,
)
from subsystems.streaming.application.ports import DependencyHealthProvider


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CompositeDependencyHealthProvider:
    def __init__(
        self,
        providers: Iterable[DependencyHealthProvider] = (),
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._clock = clock
        self._providers: dict[DependencyKind, DependencyHealthProvider] = {}
        for provider in providers:
            if provider.kind in self._providers:
                raise ValueError(f"duplicate dependency health provider: {provider.kind}")
            self._providers[provider.kind] = provider

    def get_health(self, kind: DependencyKind) -> StreamingDependencyHealth:
        provider = self._providers.get(kind)
        if provider is None:
            return NullDependencyHealthProvider(
                kind,
                clock=self._clock,
            ).get_health()
        try:
            health = provider.get_health()
        except Exception:
            return StreamingDependencyHealth(
                kind=kind,
                state=DependencyState.ERROR,
                healthy=False,
                available=False,
                checked_at=self._clock(),
                message=f"{kind.value}_health_check_failed",
            )
        if health.kind is not kind:
            return StreamingDependencyHealth(
                kind=kind,
                state=DependencyState.ERROR,
                healthy=False,
                available=False,
                checked_at=self._clock(),
                message=f"{kind.value}_health_kind_mismatch",
            )
        return health

    def list_health(self) -> tuple[StreamingDependencyHealth, ...]:
        return tuple(self.get_health(kind) for kind in DependencyKind)
