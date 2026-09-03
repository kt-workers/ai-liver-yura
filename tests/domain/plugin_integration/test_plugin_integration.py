import asyncio
from collections.abc import Callable, Sequence
from datetime import datetime, timezone

import pytest

from app.domain.activity_execution import (
    ActivityExecutionAuthority,
    ActivityExecutionCoordinator,
    ActivityInterruptibility,
    ActivityInvocation,
    ExecutionAdapterReport,
    ExecutionCancellationSignal,
    ExecutionDispatchRequest,
    ExecutionEffectEvidence,
    ExecutionEffectKind,
    ExecutionEffectUncertainty,
    ExecutionPreflightSnapshot,
)
from app.domain.contracts import (
    AuthorityRef,
    CapabilityAvailability,
    CapabilityDescriptor,
    CapabilityRequirement,
    ExecutionStatus,
    IntentKind,
    IntentRef,
    RevisionVector,
    SystemCommand,
)
from app.domain.plugin_integration import (
    PluginActivityExecutionPort,
    PluginCapabilityAdapter,
    PluginCapabilityAdapterBinding,
    PluginCapabilityPreflightPort,
    PluginIntegrationOperationalPolicy,
    PluginIntegrationTraceBuffer,
    PluginIntegrationTraceEvent,
    PluginLifecycleAdapterBinding,
    PluginLifecycleCoordinator,
)
from app.domain.plugin_registry import (
    PluginCancellationSupport,
    PluginCapabilityDeclaration,
    PluginCapabilityHealth,
    PluginHealthObservation,
    PluginHealthState,
    PluginLifecycleState,
    PluginManifest,
    PluginOperationDeclaration,
    PluginPermissionGrant,
    PluginPermissionGrantSnapshot,
    PluginPermissionRef,
    PluginRegistryAuthority,
    PluginSideEffectClass,
    PluginTimeoutSupport,
)

NOW = datetime(2026, 9, 3, 14, tzinfo=timezone.utc)
REVISIONS = RevisionVector(1)


class Clock:
    def now(self) -> datetime:
        return NOW


class BasePreflight:
    def __init__(
        self,
        capabilities: tuple[CapabilityDescriptor, ...] = (),
        before_read: Callable[[int], None] | None = None,
    ) -> None:
        self._capabilities = capabilities
        self._before_read = before_read
        self.calls = 0

    async def current_for(self, invocation: ActivityInvocation) -> ExecutionPreflightSnapshot:
        del invocation
        self.calls += 1
        if self._before_read is not None:
            self._before_read(self.calls)
        return ExecutionPreflightSnapshot(REVISIONS, self._capabilities, (), NOW)


class NativePort:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(
        self,
        request: ExecutionDispatchRequest,
        cancellation: ExecutionCancellationSignal,
    ) -> Sequence[ExecutionAdapterReport]:
        del cancellation
        self.calls += 1
        return (
            ExecutionAdapterReport(
                request.invocation.command.command_id,
                request.invocation.invocation_id,
                request.dispatch_id,
                ExecutionStatus.COMPLETED,
                NOW,
                {"code": "native_completed"},
            ),
        )


class AppliedPluginAdapter:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(
        self,
        request: ExecutionDispatchRequest,
        cancellation: ExecutionCancellationSignal,
    ) -> Sequence[ExecutionAdapterReport]:
        del cancellation
        self.calls += 1
        binding = request.bindings[0]
        effect = ExecutionEffectEvidence(
            f"effect-{request.invocation.command.command_id}",
            binding.capability_id,
            binding.descriptor_revision,
            request.invocation.operation_ref,
            ExecutionEffectKind.APPLIED,
            {"source": "fake-plugin"},
        )
        return (
            ExecutionAdapterReport(
                request.invocation.command.command_id,
                request.invocation.invocation_id,
                request.dispatch_id,
                ExecutionStatus.APPLIED,
                NOW,
                {"code": "plugin_applied"},
                (effect,),
            ),
            ExecutionAdapterReport(
                request.invocation.command.command_id,
                request.invocation.invocation_id,
                request.dispatch_id,
                ExecutionStatus.COMPLETED,
                NOW,
                {"code": "plugin_completed"},
            ),
        )


class AmbiguousTimeoutAdapter:
    async def execute(
        self,
        request: ExecutionDispatchRequest,
        cancellation: ExecutionCancellationSignal,
    ) -> Sequence[ExecutionAdapterReport]:
        del cancellation
        return (
            ExecutionAdapterReport(
                request.invocation.command.command_id,
                request.invocation.invocation_id,
                request.dispatch_id,
                ExecutionStatus.TIMED_OUT,
                NOW,
                {"code": "plugin_effect_outcome_unknown"},
                effect_uncertainty=ExecutionEffectUncertainty.POSSIBLY_APPLIED,
            ),
        )


class SlowPluginAdapter:
    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def execute(
        self,
        request: ExecutionDispatchRequest,
        cancellation: ExecutionCancellationSignal,
    ) -> Sequence[ExecutionAdapterReport]:
        del cancellation
        self.calls += 1
        self.entered.set()
        await self.release.wait()
        return (
            ExecutionAdapterReport(
                request.invocation.command.command_id,
                request.invocation.invocation_id,
                request.dispatch_id,
                ExecutionStatus.COMPLETED,
                NOW,
                {"code": "slow_plugin_completed"},
            ),
        )


class CancelledAfterInvokeAdapter:
    def __init__(self) -> None:
        self.entered = asyncio.Event()

    async def execute(
        self,
        request: ExecutionDispatchRequest,
        cancellation: ExecutionCancellationSignal,
    ) -> Sequence[ExecutionAdapterReport]:
        del request, cancellation
        self.entered.set()
        await asyncio.Event().wait()
        return ()


class FailingAfterInvokeAdapter:
    async def execute(
        self,
        request: ExecutionDispatchRequest,
        cancellation: ExecutionCancellationSignal,
    ) -> Sequence[ExecutionAdapterReport]:
        del request, cancellation
        raise RuntimeError("provider outcome is not known")


class CountingPluginAdapter:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0

    async def execute(
        self,
        request: ExecutionDispatchRequest,
        cancellation: ExecutionCancellationSignal,
    ) -> Sequence[ExecutionAdapterReport]:
        del cancellation
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        self.active -= 1
        return (
            ExecutionAdapterReport(
                request.invocation.command.command_id,
                request.invocation.invocation_id,
                request.dispatch_id,
                ExecutionStatus.COMPLETED,
                NOW,
                {"code": "counted_plugin_completed"},
            ),
        )


class LifecycleAdapter:
    def __init__(self) -> None:
        self.calls = 0

    async def stop(self, plugin_id: str, plugin_generation: int) -> None:
        assert plugin_id == "plugin-a"
        assert plugin_generation == 0
        self.calls += 1


def permission() -> PluginPermissionRef:
    return PluginPermissionRef("network_access", "search")


def plugin_manifest() -> PluginManifest:
    operation = PluginOperationDeclaration(
        "search",
        "plugin.search.input.v1",
        "plugin.search.output.v1",
        PluginSideEffectClass.OBSERVABLE_EXTERNAL,
        (permission(),),
        PluginCancellationSupport.SOFT,
        PluginTimeoutSupport(True, True),
    )
    capability = PluginCapabilityDeclaration(
        "plugin.search",
        "search",
        (operation,),
    )
    return PluginManifest(
        "plugin-a",
        "1.0.0",
        1,
        "検索Plugin",
        (capability,),
    )


def available_registry() -> PluginRegistryAuthority:
    registry = PluginRegistryAuthority()
    registry.register_manifest(plugin_manifest(), NOW)
    registry.adopt_permission_grants(
        PluginPermissionGrantSnapshot(
            0,
            (PluginPermissionGrant("plugin-a", permission()),),
            NOW,
        )
    )
    registry.apply_health_observation(
        PluginHealthObservation(
            "plugin-a",
            0,
            0,
            PluginHealthState.HEALTHY,
            (PluginCapabilityHealth("plugin.search", PluginHealthState.HEALTHY),),
            NOW,
        )
    )
    return registry


def command(
    command_id: str,
    *,
    capability_type: str,
    operation: str,
    intent_kind: IntentKind,
) -> SystemCommand:
    decision_id = f"decision-{command_id}"
    return SystemCommand(
        command_id,
        decision_id,
        IntentRef(intent_kind, f"intent-{command_id}"),
        AuthorityRef("executive", "conscious_goal_action", decision_id),
        NOW,
        REVISIONS,
        required_capabilities=(CapabilityRequirement(capability_type, operation),),
    )


def invocation(
    command_id: str,
    *,
    capability_type: str = "search",
    operation: str = "search",
    intent_kind: IntentKind = IntentKind.PLUGIN,
    operation_ref: str = "plugin.search",
) -> ActivityInvocation:
    return ActivityInvocation(
        f"invocation-{command_id}",
        command(
            command_id,
            capability_type=capability_type,
            operation=operation,
            intent_kind=intent_kind,
        ),
        operation_ref,
        {"query": "海"},
        ActivityInterruptibility.INTERRUPTIBLE,
        NOW,
    )


def coordinator(
    registry: PluginRegistryAuthority,
    adapter: PluginCapabilityAdapter,
    *,
    base_capabilities: tuple[CapabilityDescriptor, ...] = (),
    before_read: Callable[[int], None] | None = None,
    policy: PluginIntegrationOperationalPolicy | None = None,
) -> tuple[ActivityExecutionCoordinator, NativePort, PluginActivityExecutionPort]:
    base = BasePreflight(base_capabilities, before_read)
    preflight = PluginCapabilityPreflightPort(base, registry)
    native = NativePort()
    binding = PluginCapabilityAdapterBinding(
        "plugin-a",
        0,
        "plugin.search",
        adapter,
    )
    integration = PluginActivityExecutionPort(
        native,
        registry,
        (binding,),
        policy or PluginIntegrationOperationalPolicy(),
        Clock(),
    )
    return (
        ActivityExecutionCoordinator(
            preflight,
            integration,
            ActivityExecutionAuthority(),
            Clock(),
        ),
        native,
        integration,
    )


@pytest.mark.asyncio
async def test_zero_plugin_keeps_native_core_execution_path() -> None:
    native_capability = CapabilityDescriptor(
        "native.activity",
        "activity",
        ("run",),
        CapabilityAvailability.AVAILABLE,
        1,
        {},
    )
    registry = PluginRegistryAuthority()
    base = BasePreflight((native_capability,))
    preflight = PluginCapabilityPreflightPort(base, registry)
    native = NativePort()
    integration = PluginActivityExecutionPort(
        native,
        registry,
        (),
        PluginIntegrationOperationalPolicy(),
        Clock(),
    )
    owner = ActivityExecutionAuthority()
    runtime = ActivityExecutionCoordinator(preflight, integration, owner, Clock())
    result = await runtime.execute(
        invocation(
            "native-1",
            capability_type="activity",
            operation="run",
            intent_kind=IntentKind.ACTIVITY,
            operation_ref="activity.run",
        )
    )
    assert result.result.status is ExecutionStatus.COMPLETED
    assert native.calls == 1
    assert registry.snapshot(NOW).foundation_capabilities == ()


@pytest.mark.asyncio
async def test_one_plugin_executes_through_activity_fact_authority() -> None:
    registry = available_registry()
    adapter = AppliedPluginAdapter()
    runtime, native, _ = coordinator(registry, adapter)
    result = await runtime.execute(invocation("plugin-1"))
    assert result.result.status is ExecutionStatus.COMPLETED
    assert result.result.effect_refs == ("effect-plugin-1",)
    assert adapter.calls == 1
    assert native.calls == 0


@pytest.mark.asyncio
async def test_permission_revocation_before_second_preflight_blocks_plugin_invoke() -> None:
    registry = available_registry()
    adapter = AppliedPluginAdapter()

    def revoke(call_count: int) -> None:
        if call_count == 2:
            registry.adopt_permission_grants(PluginPermissionGrantSnapshot(1, (), NOW))

    runtime, _, _ = coordinator(registry, adapter, before_read=revoke)
    result = await runtime.execute(invocation("plugin-revoke"))
    assert result.result.status is ExecutionStatus.SUPERSEDED
    assert result.result.effect_refs == ()
    assert adapter.calls == 0


@pytest.mark.asyncio
async def test_ambiguous_timeout_does_not_fabricate_actual_effect() -> None:
    registry = available_registry()
    runtime, _, _ = coordinator(registry, AmbiguousTimeoutAdapter())
    result = await runtime.execute(invocation("plugin-timeout"))
    assert result.result.status is ExecutionStatus.TIMED_OUT
    assert result.result.effect_refs == ()
    assert result.effect_uncertainty is ExecutionEffectUncertainty.POSSIBLY_APPLIED
    assert result.result.details == {"code": "plugin_effect_outcome_unknown"}


@pytest.mark.asyncio
async def test_cancel_after_invoke_preserves_possible_effect_truth() -> None:
    registry = available_registry()
    adapter = CancelledAfterInvokeAdapter()
    runtime, _, _ = coordinator(registry, adapter)
    task = asyncio.create_task(runtime.execute(invocation("plugin-cancel-after-invoke")))
    await adapter.entered.wait()
    await runtime.cancel("plugin-cancel-after-invoke", "user_cancelled")
    result = await task
    assert result.result.status is ExecutionStatus.CANCELLED
    assert result.result.effect_refs == ()
    assert result.effect_uncertainty is ExecutionEffectUncertainty.POSSIBLY_APPLIED


@pytest.mark.asyncio
async def test_adapter_failure_after_invoke_keeps_unknown_effect_truth() -> None:
    registry = available_registry()
    runtime, _, _ = coordinator(registry, FailingAfterInvokeAdapter())
    result = await runtime.execute(invocation("plugin-failure-after-invoke"))
    assert result.result.status is ExecutionStatus.FAILED
    assert result.result.effect_refs == ()
    assert result.effect_uncertainty is ExecutionEffectUncertainty.UNKNOWN
    assert result.result.details == {"code": "plugin_adapter_failure"}


@pytest.mark.asyncio
async def test_slow_plugin_does_not_block_unrelated_native_execution() -> None:
    registry = available_registry()
    slow = SlowPluginAdapter()
    native_capability = CapabilityDescriptor(
        "native.activity",
        "activity",
        ("run",),
        CapabilityAvailability.AVAILABLE,
        1,
        {},
    )
    runtime, native, _ = coordinator(
        registry,
        slow,
        base_capabilities=(native_capability,),
    )
    plugin_task = asyncio.create_task(runtime.execute(invocation("plugin-slow")))
    await slow.entered.wait()
    native_result = await asyncio.wait_for(
        runtime.execute(
            invocation(
                "native-fast",
                capability_type="activity",
                operation="run",
                intent_kind=IntentKind.ACTIVITY,
                operation_ref="activity.run",
            )
        ),
        timeout=1.0,
    )
    assert native_result.result.status is ExecutionStatus.COMPLETED
    assert native.calls == 1
    slow.release.set()
    plugin_result = await plugin_task
    assert plugin_result.result.status is ExecutionStatus.COMPLETED


@pytest.mark.asyncio
async def test_per_capability_concurrency_is_bounded() -> None:
    registry = available_registry()
    adapter = CountingPluginAdapter()
    policy = PluginIntegrationOperationalPolicy(
        max_in_flight_per_plugin=2,
        max_in_flight_per_capability=1,
    )
    runtime, _, _ = coordinator(registry, adapter, policy=policy)
    first, second = await asyncio.gather(
        runtime.execute(invocation("plugin-count-1")),
        runtime.execute(invocation("plugin-count-2")),
    )
    assert first.result.status is ExecutionStatus.COMPLETED
    assert second.result.status is ExecutionStatus.COMPLETED
    assert adapter.max_active == 1


def test_event_projection_overflow_is_explicit() -> None:
    policy = PluginIntegrationOperationalPolicy(event_projection_capacity=1)
    trace = PluginIntegrationTraceBuffer(policy)
    event = PluginIntegrationTraceEvent(
        "plugin_execution_started",
        NOW,
        "plugin-a",
        0,
        "plugin.search",
        "command-1",
        {},
    )
    assert trace.publish(event) is True
    assert trace.publish(event) is False
    snapshot = trace.snapshot()
    assert len(snapshot.events) == 1
    assert snapshot.rejected_event_count == 1


@pytest.mark.asyncio
async def test_stop_fence_closes_new_availability_and_waits_for_inflight() -> None:
    registry = available_registry()
    slow = SlowPluginAdapter()
    runtime, _, integration = coordinator(registry, slow)
    lifecycle_adapter = LifecycleAdapter()
    lifecycle = PluginLifecycleCoordinator(
        registry,
        integration,
        (PluginLifecycleAdapterBinding("plugin-a", 0, lifecycle_adapter),),
        PluginIntegrationOperationalPolicy(),
        Clock(),
    )

    execution = asyncio.create_task(runtime.execute(invocation("plugin-stop")))
    await slow.entered.wait()
    stop_task = asyncio.create_task(lifecycle.stop("plugin-a"))
    await asyncio.sleep(0)
    during_stop = registry.snapshot(NOW)
    assert during_stop.plugins[0].lifecycle_state is PluginLifecycleState.STOPPING
    capabilities = during_stop.foundation_capabilities
    assert len(capabilities) == 1
    assert capabilities[0].capability_id == "plugin.search"
    assert capabilities[0].availability is CapabilityAvailability.UNAVAILABLE
    assert stop_task.done() is False

    slow.release.set()
    result = await execution
    assert result.result.status is ExecutionStatus.COMPLETED
    assert await stop_task is True
    after = registry.snapshot(NOW)
    assert after.plugins[0].lifecycle_state is PluginLifecycleState.STOPPED
    assert lifecycle_adapter.calls == 1


@pytest.mark.asyncio
async def test_waiting_execution_revalidates_after_stop_fence() -> None:
    registry = available_registry()
    slow = SlowPluginAdapter()
    policy = PluginIntegrationOperationalPolicy(
        max_in_flight_per_plugin=1,
        max_in_flight_per_capability=1,
    )
    runtime, _, integration = coordinator(registry, slow, policy=policy)
    lifecycle_adapter = LifecycleAdapter()
    lifecycle = PluginLifecycleCoordinator(
        registry,
        integration,
        (PluginLifecycleAdapterBinding("plugin-a", 0, lifecycle_adapter),),
        policy,
        Clock(),
    )

    first = asyncio.create_task(runtime.execute(invocation("plugin-first")))
    await slow.entered.wait()
    second = asyncio.create_task(runtime.execute(invocation("plugin-second")))
    await asyncio.sleep(0)
    stop_task = asyncio.create_task(lifecycle.stop("plugin-a"))
    await asyncio.sleep(0)

    slow.release.set()
    first_result = await first
    second_result = await second
    assert first_result.result.status is ExecutionStatus.COMPLETED
    assert second_result.result.status is ExecutionStatus.FAILED
    assert second_result.effect_uncertainty is ExecutionEffectUncertainty.NONE
    assert slow.calls == 1
    assert await stop_task is True


@pytest.mark.asyncio
async def test_waiting_execution_revalidates_after_permission_revocation() -> None:
    registry = available_registry()
    slow = SlowPluginAdapter()
    policy = PluginIntegrationOperationalPolicy(
        max_in_flight_per_plugin=1,
        max_in_flight_per_capability=1,
    )
    runtime, _, _ = coordinator(registry, slow, policy=policy)

    first = asyncio.create_task(runtime.execute(invocation("plugin-permission-first")))
    await slow.entered.wait()
    second = asyncio.create_task(runtime.execute(invocation("plugin-permission-second")))
    await asyncio.sleep(0)
    registry.adopt_permission_grants(PluginPermissionGrantSnapshot(1, (), NOW))

    slow.release.set()
    first_result = await first
    second_result = await second
    assert first_result.result.status is ExecutionStatus.COMPLETED
    assert second_result.result.status is ExecutionStatus.FAILED
    assert second_result.effect_uncertainty is ExecutionEffectUncertainty.NONE
    assert slow.calls == 1
