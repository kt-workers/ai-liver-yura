import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

from app.domain.contracts import CapabilityAvailability
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

NOW = datetime(2026, 8, 17, tzinfo=timezone.utc)
LATER = NOW + timedelta(seconds=1)


def permission() -> PluginPermissionRef:
    return PluginPermissionRef("network_access", "scope-a")


def manifest(
    *,
    plugin_id: str = "plugin-a",
    capability_id: str = "capability-a",
) -> PluginManifest:
    operation = PluginOperationDeclaration(
        "execute",
        "plugin.input.v1",
        "plugin.output.v1",
        PluginSideEffectClass.OBSERVABLE_EXTERNAL,
        (permission(),),
        PluginCancellationSupport.SOFT,
        PluginTimeoutSupport(True, True),
    )
    return PluginManifest(
        plugin_id,
        "1.0.0",
        1,
        "Plugin",
        (PluginCapabilityDeclaration(capability_id, "plugin", (operation,)),),
    )


def grants(
    revision: int,
    *,
    permissions: tuple[PluginPermissionRef, ...] | None = None,
) -> PluginPermissionGrantSnapshot:
    selected = (permission(),) if permissions is None else permissions
    return PluginPermissionGrantSnapshot(
        revision,
        tuple(PluginPermissionGrant("plugin-a", item) for item in selected),
        NOW + timedelta(seconds=revision),
    )


def health(revision: int = 0) -> PluginHealthObservation:
    return PluginHealthObservation(
        "plugin-a",
        0,
        revision,
        PluginHealthState.HEALTHY,
        (PluginCapabilityHealth("capability-a", PluginHealthState.HEALTHY),),
        NOW + timedelta(seconds=revision),
    )


def available_registry() -> PluginRegistryAuthority:
    registry = PluginRegistryAuthority()
    registry.register_manifest(manifest(), NOW)
    registry.adopt_permission_grants(grants(0))
    registry.apply_health_observation(health())
    return registry


def test_concurrent_duplicate_register_has_at_most_one_success() -> None:
    registry = PluginRegistryAuthority()
    gate = Barrier(2)

    def attempt(_: int) -> str:
        gate.wait()
        try:
            registry.register_manifest(manifest(), NOW)
            return "accepted"
        except ValueError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(attempt, (1, 2)))

    assert outcomes.count("accepted") == 1
    assert outcomes.count("rejected") == 1
    assert len(registry.snapshot(NOW).plugins) == 1


def test_concurrent_health_and_stop_cannot_resurrect_availability() -> None:
    registry = available_registry()
    gate = Barrier(2)

    def refresh_health() -> None:
        gate.wait()
        registry.apply_health_observation(health(1))

    def stop() -> None:
        gate.wait()
        registry.begin_stop("plugin-a", LATER)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(refresh_health), executor.submit(stop)]
        for future in futures:
            future.result()

    snapshot = registry.snapshot(LATER)
    assert snapshot.plugins[0].lifecycle_state is PluginLifecycleState.STOPPING
    assert snapshot.foundation_capabilities[0].availability is CapabilityAvailability.UNAVAILABLE


def test_permission_refresh_and_unregister_are_atomically_ordered() -> None:
    registry = available_registry()
    registry.begin_stop("plugin-a", NOW)
    registry.mark_stopped("plugin-a", NOW)
    before = registry.snapshot(NOW).registry_revision
    gate = Barrier(2)

    def refresh_permissions() -> None:
        gate.wait()
        registry.adopt_permission_grants(grants(1, permissions=()))

    def unregister() -> None:
        gate.wait()
        registry.unregister("plugin-a", LATER)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(refresh_permissions), executor.submit(unregister)]
        for future in futures:
            future.result()

    snapshot = registry.snapshot(LATER)
    assert snapshot.plugins == ()
    assert snapshot.capabilities == ()
    assert snapshot.foundation_capabilities == ()
    assert snapshot.registry_revision >= before + 1


def test_old_generation_health_is_rejected_after_concurrent_style_readd_boundary() -> None:
    registry = available_registry()
    registry.begin_stop("plugin-a", NOW)
    registry.mark_stopped("plugin-a", NOW)
    registry.unregister("plugin-a", NOW)
    registry.register_manifest(manifest(), LATER)

    stale = PluginHealthObservation(
        "plugin-a",
        0,
        2,
        PluginHealthState.HEALTHY,
        (PluginCapabilityHealth("capability-a", PluginHealthState.HEALTHY),),
        LATER,
    )
    try:
        registry.apply_health_observation(stale)
    except ValueError as exc:
        assert "generation" in str(exc)
    else:
        raise AssertionError("old generation health must be rejected")


def test_external_lifecycle_await_does_not_hold_registry_lock() -> None:
    registry = available_registry()

    async def lifecycle_provider_call() -> None:
        registry.begin_stop("plugin-a", NOW)
        await asyncio.sleep(0.05)
        registry.mark_stopped("plugin-a", LATER)

    async def scenario() -> None:
        task = asyncio.create_task(lifecycle_provider_call())
        await asyncio.sleep(0)
        snapshot = await asyncio.wait_for(
            asyncio.to_thread(registry.snapshot, NOW),
            timeout=0.2,
        )
        assert snapshot.plugins[0].lifecycle_state is PluginLifecycleState.STOPPING
        await task

    asyncio.run(scenario())
