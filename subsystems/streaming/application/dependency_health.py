"""Read-only coordination for Streaming dependency health."""

from app.integrations.streaming import (
    DependencyKind,
    StreamingCapability,
    StreamingDependencyHealth,
)
from subsystems.streaming.application.ports import DependencyHealthCatalog


class DependencyHealthService:
    def __init__(self, catalog: DependencyHealthCatalog) -> None:
        self._catalog = catalog

    def get(self, kind: DependencyKind) -> StreamingDependencyHealth:
        return self._catalog.get_health(kind)

    def list(self) -> tuple[StreamingDependencyHealth, ...]:
        return self._catalog.list_health()

    def available_capabilities(self) -> frozenset[StreamingCapability]:
        return frozenset(
            capability
            for health in self.list()
            if health.available
            for capability in health.capabilities
        )

    def component_health(self) -> dict[str, bool]:
        return {health.kind.value: health.healthy for health in self.list()}
