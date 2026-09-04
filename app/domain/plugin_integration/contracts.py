from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Protocol

from app.domain.activity_execution import (
    ActivityExecutionPort,
    ExecutionAdapterReport,
    ExecutionCancellationSignal,
    ExecutionDispatchRequest,
    ExecutionPreflightPort,
    ExecutionPreflightSnapshot,
)
from app.domain.contracts.common import JsonValue, freeze_json, require_aware, require_identifier
from app.domain.plugin_registry import PluginRegistryAuthority, PluginRegistrySnapshot


@dataclass(frozen=True, slots=True)
class PluginIntegrationOperationalPolicy:
    policy_id: str = "v2.plugin-integration.default"
    policy_revision: int = 1
    max_in_flight_per_plugin: int = 8
    max_in_flight_per_capability: int = 4
    event_projection_capacity: int = 128
    lifecycle_operation_timeout_seconds: float = 30.0
    diagnostic_min_interval_seconds: float = 5.0

    def __post_init__(self) -> None:
        require_identifier(self.policy_id, "policy_id")
        if type(self.policy_revision) is not int or self.policy_revision < 0:
            raise ValueError("policy_revision は0以上の整数でなければなりません")
        for name in (
            "max_in_flight_per_plugin",
            "max_in_flight_per_capability",
            "event_projection_capacity",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} は1以上の整数でなければなりません")
        timeout = self.lifecycle_operation_timeout_seconds
        if (
            type(timeout) not in (int, float)
            or isinstance(timeout, bool)
            or not isfinite(float(timeout))
            or float(timeout) <= 0
        ):
            raise ValueError("lifecycle_operation_timeout_seconds は正の有限数でなければなりません")
        interval = self.diagnostic_min_interval_seconds
        if (
            type(interval) not in (int, float)
            or isinstance(interval, bool)
            or not isfinite(float(interval))
            or float(interval) < 0
        ):
            raise ValueError("diagnostic_min_interval_seconds は0以上の有限数でなければなりません")


class PluginRegistryReadPort(Protocol):
    def snapshot(self, captured_at: datetime | None = None) -> PluginRegistrySnapshot: ...


class PluginCapabilityAdapter(Protocol):
    async def execute(
        self,
        request: ExecutionDispatchRequest,
        cancellation: ExecutionCancellationSignal,
    ) -> Sequence[ExecutionAdapterReport]: ...


@dataclass(frozen=True, slots=True)
class PluginCapabilityAdapterBinding:
    plugin_id: str
    plugin_generation: int
    capability_id: str
    adapter: PluginCapabilityAdapter

    def __post_init__(self) -> None:
        require_identifier(self.plugin_id, "plugin_id")
        require_identifier(self.capability_id, "capability_id")
        if type(self.plugin_generation) is not int or self.plugin_generation < 0:
            raise ValueError("plugin_generation は0以上の整数でなければなりません")


class PluginLifecycleAdapter(Protocol):
    async def stop(self, plugin_id: str, plugin_generation: int) -> None: ...


@dataclass(frozen=True, slots=True)
class PluginLifecycleAdapterBinding:
    plugin_id: str
    plugin_generation: int
    adapter: PluginLifecycleAdapter

    def __post_init__(self) -> None:
        require_identifier(self.plugin_id, "plugin_id")
        if type(self.plugin_generation) is not int or self.plugin_generation < 0:
            raise ValueError("plugin_generation は0以上の整数でなければなりません")


@dataclass(frozen=True, slots=True)
class PluginIntegrationTraceEvent:
    event_type: str
    occurred_at: datetime
    plugin_id: str
    plugin_generation: int
    capability_id: str
    command_id: str
    details: JsonValue

    def __post_init__(self) -> None:
        for name in ("event_type", "plugin_id", "capability_id", "command_id"):
            require_identifier(getattr(self, name), name)
        require_aware(self.occurred_at, "occurred_at")
        if type(self.plugin_generation) is not int or self.plugin_generation < 0:
            raise ValueError("plugin_generation は0以上の整数でなければなりません")
        object.__setattr__(self, "details", freeze_json(self.details))


@dataclass(frozen=True, slots=True)
class PluginIntegrationTraceSnapshot:
    events: tuple[PluginIntegrationTraceEvent, ...]
    rejected_event_count: int
    suppressed_diagnostic_count: int


class PluginIntegrationClock(Protocol):
    def now(self) -> datetime: ...


__all__ = [
    "ActivityExecutionPort",
    "ExecutionPreflightPort",
    "ExecutionPreflightSnapshot",
    "PluginCapabilityAdapter",
    "PluginCapabilityAdapterBinding",
    "PluginIntegrationClock",
    "PluginIntegrationOperationalPolicy",
    "PluginIntegrationTraceEvent",
    "PluginIntegrationTraceSnapshot",
    "PluginLifecycleAdapter",
    "PluginLifecycleAdapterBinding",
    "PluginRegistryAuthority",
    "PluginRegistryReadPort",
]
