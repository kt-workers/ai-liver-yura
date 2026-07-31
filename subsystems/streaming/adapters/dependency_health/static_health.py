"""Static dependency health provider for tests and future integration adapters."""

from app.integrations.streaming import DependencyKind, StreamingDependencyHealth


class StaticDependencyHealthProvider:
    def __init__(self, health: StreamingDependencyHealth) -> None:
        self._health = health

    @property
    def kind(self) -> DependencyKind:
        return self._health.kind

    def get_health(self) -> StreamingDependencyHealth:
        return self._health
