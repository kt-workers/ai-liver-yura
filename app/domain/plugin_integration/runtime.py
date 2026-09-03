from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.domain.activity_execution import (
    ActivityExecutionPort,
    ActivityInvocation,
    CapabilityBinding,
    ExecutionAdapterReport,
    ExecutionCancellationSignal,
    ExecutionDispatchRequest,
    ExecutionEffectUncertainty,
    ExecutionPreflightPort,
    ExecutionPreflightSnapshot,
)
from app.domain.contracts import CapabilityAvailability, ExecutionStatus
from app.domain.plugin_registry import (
    PluginLifecycleState,
    PluginRegistryAuthority,
    PluginRegistrySnapshot,
)
from app.domain.plugin_registry.contracts import RegisteredCapabilityView

from .contracts import (
    PluginCapabilityAdapterBinding,
    PluginIntegrationClock,
    PluginIntegrationOperationalPolicy,
    PluginIntegrationTraceEvent,
    PluginIntegrationTraceSnapshot,
    PluginLifecycleAdapterBinding,
    PluginRegistryReadPort,
)


@dataclass(slots=True)
class _InflightState:
    count: int
    idle: asyncio.Event


class PluginIntegrationTraceBuffer:
    def __init__(self, policy: PluginIntegrationOperationalPolicy) -> None:
        self._policy = policy
        self._events: list[PluginIntegrationTraceEvent] = []
        self._rejected_event_count = 0
        self._suppressed_diagnostic_count = 0
        self._last_diagnostic_at: dict[str, datetime] = {}

    def publish(self, event: PluginIntegrationTraceEvent) -> bool:
        if len(self._events) >= self._policy.event_projection_capacity:
            self._rejected_event_count += 1
            return False
        self._events.append(event)
        return True

    def publish_diagnostic(self, key: str, event: PluginIntegrationTraceEvent) -> bool:
        previous = self._last_diagnostic_at.get(key)
        if previous is not None:
            elapsed = (event.occurred_at - previous).total_seconds()
            if elapsed < self._policy.diagnostic_min_interval_seconds:
                self._suppressed_diagnostic_count += 1
                return False
        self._last_diagnostic_at[key] = event.occurred_at
        return self.publish(event)

    def snapshot(self) -> PluginIntegrationTraceSnapshot:
        return PluginIntegrationTraceSnapshot(
            tuple(self._events),
            self._rejected_event_count,
            self._suppressed_diagnostic_count,
        )


class PluginCapabilityPreflightPort:
    """Coreのcurrent preflightへPlugin Capability公開結果だけを重ねる。"""

    def __init__(
        self,
        base: ExecutionPreflightPort,
        registry: PluginRegistryReadPort,
    ) -> None:
        self._base = base
        self._registry = registry

    async def current_for(self, invocation: ActivityInvocation) -> ExecutionPreflightSnapshot:
        base = await self._base.current_for(invocation)
        registry = self._registry.snapshot(base.captured_at)
        plugin_descriptors = registry.foundation_capabilities
        if not plugin_descriptors:
            return base
        base_ids = {item.capability_id for item in base.capabilities}
        collisions = base_ids & {item.capability_id for item in plugin_descriptors}
        if collisions:
            raise ValueError("Plugin Capability IDがCore Capabilityと衝突しています")
        return ExecutionPreflightSnapshot(
            base.revisions,
            (*base.capabilities, *plugin_descriptors),
            base.preconditions,
            base.captured_at,
        )


class PluginActivityExecutionPort:
    """#329の実行PortとしてPlugin Capabilityだけをtrusted bindingへdispatchする。"""

    def __init__(
        self,
        native_port: ActivityExecutionPort,
        registry: PluginRegistryReadPort,
        adapter_bindings: tuple[PluginCapabilityAdapterBinding, ...],
        policy: PluginIntegrationOperationalPolicy,
        clock: PluginIntegrationClock,
        trace: PluginIntegrationTraceBuffer | None = None,
    ) -> None:
        self._native_port = native_port
        self._registry = registry
        self._policy = policy
        self._clock = clock
        self._trace = trace or PluginIntegrationTraceBuffer(policy)
        keys = [
            (item.plugin_id, item.plugin_generation, item.capability_id)
            for item in adapter_bindings
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("Plugin Capability Adapter bindingは重複できません")
        self._adapter_bindings = adapter_bindings
        self._configured_plugin_capability_ids = frozenset(
            item.capability_id for item in adapter_bindings
        )
        self._plugin_semaphores: dict[str, asyncio.Semaphore] = {}
        self._capability_semaphores: dict[str, asyncio.Semaphore] = {}
        self._inflight: dict[str, _InflightState] = {}
        self._state_lock = asyncio.Lock()

    @property
    def trace(self) -> PluginIntegrationTraceBuffer:
        return self._trace

    async def execute(
        self,
        request: ExecutionDispatchRequest,
        cancellation: ExecutionCancellationSignal,
    ) -> Sequence[ExecutionAdapterReport]:
        current = self._registry.snapshot(self._clock.now())
        current_capability_ids = {
            item.declaration.capability_id for item in current.capabilities
        }
        plugin_bindings = tuple(
            item
            for item in request.bindings
            if item.capability_id in current_capability_ids
            or item.capability_id in self._configured_plugin_capability_ids
        )
        if not plugin_bindings:
            return await self._native_port.execute(request, cancellation)
        if len(plugin_bindings) != 1:
            return (self._failure(request, "plugin_capability_binding_ambiguous"),)

        selected = plugin_bindings[0]
        current_view = self._find_current_view(current, selected)
        failure = self._validate_current_view(current_view, selected)
        if failure is not None:
            return (self._failure(request, failure),)
        assert current_view is not None
        adapter_binding = self._find_adapter_binding(current_view)
        if adapter_binding is None:
            return (self._failure(request, "plugin_adapter_binding_missing"),)
        if cancellation.cancelled:
            return (self._cancelled(request, "plugin_cancelled_before_invoke"),)

        plugin_semaphore = self._plugin_semaphores.setdefault(
            current_view.plugin_id,
            asyncio.Semaphore(self._policy.max_in_flight_per_plugin),
        )
        capability_semaphore = self._capability_semaphores.setdefault(
            current_view.declaration.capability_id,
            asyncio.Semaphore(self._policy.max_in_flight_per_capability),
        )
        async with plugin_semaphore, capability_semaphore:
            final_snapshot = self._registry.snapshot(self._clock.now())
            final_view = self._find_current_view(final_snapshot, selected)
            failure = self._validate_current_view(final_view, selected)
            if failure is not None:
                return (self._failure(request, failure),)
            assert final_view is not None
            final_adapter_binding = self._find_adapter_binding(final_view)
            if final_adapter_binding is not adapter_binding:
                return (self._failure(request, "plugin_adapter_binding_changed"),)
            if cancellation.cancelled:
                return (self._cancelled(request, "plugin_cancelled_before_invoke"),)

            await self._inflight_started(final_view.plugin_id)
            self._trace.publish(
                PluginIntegrationTraceEvent(
                    "plugin_execution_started",
                    self._clock.now(),
                    final_view.plugin_id,
                    final_view.plugin_generation,
                    final_view.declaration.capability_id,
                    request.invocation.command.command_id,
                    {
                        "descriptor_revision": selected.descriptor_revision,
                        "operation_id": selected.requirement.operation,
                    },
                )
            )
            try:
                reports = tuple(
                    await adapter_binding.adapter.execute(request, cancellation)
                )
            except asyncio.CancelledError:
                return (
                    self._cancelled(
                        request,
                        "plugin_adapter_cancelled_after_invoke",
                        ExecutionEffectUncertainty.POSSIBLY_APPLIED,
                    ),
                )
            except Exception:
                self._publish_failure_diagnostic(
                    final_view.plugin_id,
                    final_view.plugin_generation,
                    final_view.declaration.capability_id,
                    request,
                    "plugin_adapter_failure",
                )
                return (
                    self._failure(
                        request,
                        "plugin_adapter_failure",
                        ExecutionEffectUncertainty.UNKNOWN,
                    ),
                )
            finally:
                await self._inflight_finished(final_view.plugin_id)

        self._trace.publish(
            PluginIntegrationTraceEvent(
                "plugin_execution_completed",
                self._clock.now(),
                final_view.plugin_id,
                final_view.plugin_generation,
                final_view.declaration.capability_id,
                request.invocation.command.command_id,
                {"report_count": len(reports)},
            )
        )
        return reports

    async def wait_for_plugin_idle(self, plugin_id: str, timeout_seconds: float) -> bool:
        async with self._state_lock:
            state = self._inflight.get(plugin_id)
            if state is None or state.count == 0:
                return True
            idle = state.idle
        try:
            await asyncio.wait_for(idle.wait(), timeout=timeout_seconds)
        except TimeoutError:
            return False
        return True

    async def _inflight_started(self, plugin_id: str) -> None:
        async with self._state_lock:
            state = self._inflight.get(plugin_id)
            if state is None:
                state = _InflightState(0, asyncio.Event())
                state.idle.set()
                self._inflight[plugin_id] = state
            state.count += 1
            state.idle.clear()

    async def _inflight_finished(self, plugin_id: str) -> None:
        async with self._state_lock:
            state = self._inflight[plugin_id]
            state.count -= 1
            if state.count == 0:
                state.idle.set()

    @staticmethod
    def _find_current_view(
        snapshot: PluginRegistrySnapshot,
        selected: CapabilityBinding,
    ) -> RegisteredCapabilityView | None:
        return next(
            (
                item
                for item in snapshot.capabilities
                if item.declaration.capability_id == selected.capability_id
            ),
            None,
        )

    @staticmethod
    def _validate_current_view(
        current_view: RegisteredCapabilityView | None,
        selected: CapabilityBinding,
    ) -> str | None:
        if current_view is None:
            return "plugin_capability_unavailable"
        if current_view.capability_revision != selected.descriptor_revision:
            return "plugin_capability_revision_changed"
        available = current_view.effective_availability is CapabilityAvailability.AVAILABLE
        degraded_allowed = (
            current_view.effective_availability is CapabilityAvailability.DEGRADED
            and selected.requirement.allow_degraded
        )
        if not (available or degraded_allowed):
            return "plugin_capability_unavailable"
        if not any(
            item.operation_id == selected.requirement.operation
            for item in current_view.permitted_operations
        ):
            return "plugin_operation_not_permitted"
        return None

    def _find_adapter_binding(
        self,
        current_view: RegisteredCapabilityView,
    ) -> PluginCapabilityAdapterBinding | None:
        return next(
            (
                item
                for item in self._adapter_bindings
                if item.plugin_id == current_view.plugin_id
                and item.plugin_generation == current_view.plugin_generation
                and item.capability_id == current_view.declaration.capability_id
            ),
            None,
        )

    def _failure(
        self,
        request: ExecutionDispatchRequest,
        code: str,
        effect_uncertainty: ExecutionEffectUncertainty = ExecutionEffectUncertainty.NONE,
    ) -> ExecutionAdapterReport:
        return ExecutionAdapterReport(
            request.invocation.command.command_id,
            request.invocation.invocation_id,
            request.dispatch_id,
            ExecutionStatus.FAILED,
            self._clock.now(),
            {"code": code},
            effect_uncertainty=effect_uncertainty,
        )

    def _cancelled(
        self,
        request: ExecutionDispatchRequest,
        code: str,
        effect_uncertainty: ExecutionEffectUncertainty = ExecutionEffectUncertainty.NONE,
    ) -> ExecutionAdapterReport:
        return ExecutionAdapterReport(
            request.invocation.command.command_id,
            request.invocation.invocation_id,
            request.dispatch_id,
            ExecutionStatus.CANCELLED,
            self._clock.now(),
            {"code": code},
            effect_uncertainty=effect_uncertainty,
        )

    def _publish_failure_diagnostic(
        self,
        plugin_id: str,
        plugin_generation: int,
        capability_id: str,
        request: ExecutionDispatchRequest,
        code: str,
    ) -> None:
        event = PluginIntegrationTraceEvent(
            "plugin_execution_failed",
            self._clock.now(),
            plugin_id,
            plugin_generation,
            capability_id,
            request.invocation.command.command_id,
            {"code": code},
        )
        self._trace.publish_diagnostic(f"{plugin_id}:{capability_id}:{code}", event)


class PluginLifecycleCoordinator:
    """STOPPING fenceを先に閉じ、外部stop成功時だけSTOPPEDへ進める。"""

    def __init__(
        self,
        registry: PluginRegistryAuthority,
        execution_port: PluginActivityExecutionPort,
        adapter_bindings: tuple[PluginLifecycleAdapterBinding, ...],
        policy: PluginIntegrationOperationalPolicy,
        clock: PluginIntegrationClock,
    ) -> None:
        self._registry = registry
        self._execution_port = execution_port
        self._adapter_bindings = adapter_bindings
        self._policy = policy
        self._clock = clock

    async def stop(self, plugin_id: str) -> bool:
        before = self._registry.snapshot(self._clock.now())
        plugin = next(
            (item for item in before.plugins if item.manifest.plugin_id == plugin_id),
            None,
        )
        if plugin is None:
            raise ValueError("停止対象Pluginが登録されていません")
        if plugin.lifecycle_state is PluginLifecycleState.STOPPED:
            return True
        self._registry.begin_stop(plugin_id, self._clock.now())
        idle = await self._execution_port.wait_for_plugin_idle(
            plugin_id,
            self._policy.lifecycle_operation_timeout_seconds,
        )
        if not idle:
            return False
        binding = next(
            (
                item
                for item in self._adapter_bindings
                if item.plugin_id == plugin_id
                and item.plugin_generation == plugin.plugin_generation
            ),
            None,
        )
        if binding is not None:
            try:
                await asyncio.wait_for(
                    binding.adapter.stop(plugin_id, plugin.plugin_generation),
                    timeout=self._policy.lifecycle_operation_timeout_seconds,
                )
            except Exception:
                return False
        self._registry.mark_stopped(plugin_id, self._clock.now())
        return True
