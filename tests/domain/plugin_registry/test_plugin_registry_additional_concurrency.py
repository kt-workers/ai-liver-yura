import asyncio
from datetime import datetime, timezone

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


def permission() -> PluginPermissionRef:
    return PluginPermissionRef("network_access", "scope-a")


def manifest() -> PluginManifest:
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
        "plugin-a",
        "1.0.0",
        1,
        "Plugin",
        (PluginCapabilityDeclaration("capability-a", "plugin", (operation,)),),
    )


def available_registry() -> PluginRegistryAuthority:
    registry = PluginRegistryAuthority()
    registry.register_manifest(manifest(), NOW)
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
            (PluginCapabilityHealth("capability-a", PluginHealthState.HEALTHY),),
            NOW,
        )
    )
    return registry


def test_slow_lifecycle_provider_wait_does_not_block_unrelated_async_work() -> None:
    registry = available_registry()

    async def scenario() -> None:
        heartbeat = 0

        async def provider_stop() -> None:
            registry.begin_stop("plugin-a", NOW)
            await asyncio.sleep(0.05)
            registry.mark_stopped("plugin-a", NOW)

        async def unrelated_work() -> None:
            nonlocal heartbeat
            for _ in range(3):
                await asyncio.sleep(0.005)
                heartbeat += 1

        provider_task = asyncio.create_task(provider_stop())
        unrelated_task = asyncio.create_task(unrelated_work())
        await asyncio.sleep(0)

        snapshot = await asyncio.wait_for(
            asyncio.to_thread(registry.snapshot, NOW),
            timeout=0.2,
        )
        assert snapshot.plugins[0].lifecycle_state is PluginLifecycleState.STOPPING

        await unrelated_task
        assert heartbeat == 3
        await provider_task

    asyncio.run(scenario())


def test_provider_stop_failure_preserves_stopping_registry_state() -> None:
    registry = available_registry()
    registry.begin_stop("plugin-a", NOW)
    before = registry.snapshot(NOW)

    async def failing_provider_stop() -> None:
        await asyncio.sleep(0)
        raise RuntimeError("provider stop failed")

    async def scenario() -> None:
        try:
            await failing_provider_stop()
        except RuntimeError:
            pass

    asyncio.run(scenario())
    after = registry.snapshot(NOW)

    assert after.registry_revision == before.registry_revision
    assert after.plugins == before.plugins
    assert after.capabilities == before.capabilities
    assert after.plugins[0].lifecycle_state is PluginLifecycleState.STOPPING
    assert after.foundation_capabilities[0].availability is CapabilityAvailability.UNAVAILABLE
