"""Core-independent preparation health adapters."""

from subsystems.streaming.domain import HealthCheckItem, HealthStatus


class StaticPreparationHealthAdapter:
    def __init__(self, component: str, available: bool = False) -> None:
        self._component = component
        self._available = available

    async def check(self, *, required: bool) -> HealthCheckItem:
        healthy = self._available or not required
        return HealthCheckItem(
            check_id=f"{self._component}.available",
            component=self._component,
            status=HealthStatus.HEALTHY if healthy else HealthStatus.UNAVAILABLE,
            required=required,
            summary="available" if healthy else "not connected",
            failure_reason=(None if healthy else f"{self._component}.not_connected"),
        )
