"""Core-independent dependency health providers."""

from subsystems.streaming.adapters.dependency_health.composite import (
    CompositeDependencyHealthProvider,
)
from subsystems.streaming.adapters.dependency_health.null_health import (
    NullDependencyHealthProvider,
)
from subsystems.streaming.adapters.dependency_health.static_health import (
    StaticDependencyHealthProvider,
)

__all__ = [
    "CompositeDependencyHealthProvider",
    "NullDependencyHealthProvider",
    "StaticDependencyHealthProvider",
]
