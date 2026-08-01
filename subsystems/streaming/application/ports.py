"""Internal runtime port implemented by Fake and future adapters."""

from collections.abc import Sequence
from typing import Protocol

from app.integrations.streaming import (
    DependencyKind,
    StreamingCapabilities,
    StreamingCursor,
    StreamingDependencyHealth,
    StreamingEventEnvelope,
    StreamingHealth,
    StreamingOperationRequest,
    StreamingOperationResult,
    StreamingStatus,
)


class DependencyHealthProvider(Protocol):
    """Read-only health provider for one external dependency."""

    @property
    def kind(self) -> DependencyKind: ...

    def get_health(self) -> StreamingDependencyHealth: ...


class DependencyHealthCatalog(Protocol):
    """Deterministic aggregate of all dependency health providers."""

    def get_health(self, kind: DependencyKind) -> StreamingDependencyHealth: ...

    def list_health(self) -> tuple[StreamingDependencyHealth, ...]: ...


class StreamingRuntime(Protocol):
    """Runtime behavior required by the Application Service."""

    async def get_status(self) -> StreamingStatus:
        """Return the normalized runtime status."""
        ...

    async def get_health(self) -> StreamingHealth:
        """Return normalized runtime health."""
        ...

    async def get_capabilities(self) -> StreamingCapabilities:
        """Return currently available public capabilities."""
        ...

    async def get_dependency_health(
        self,
        kind: DependencyKind,
    ) -> StreamingDependencyHealth:
        """Return normalized health for one dependency."""
        ...

    async def list_dependency_health(
        self,
    ) -> tuple[StreamingDependencyHealth, ...]:
        """Return dependency health in stable kind order."""
        ...

    async def execute_operation(
        self,
        request: StreamingOperationRequest,
    ) -> StreamingOperationResult:
        """Execute a public operation without raising for normal rejection."""
        ...

    async def read_events(
        self,
        after: StreamingCursor | None = None,
    ) -> Sequence[StreamingEventEnvelope]:
        """Read retained Events after an optional opaque cursor."""
        ...
