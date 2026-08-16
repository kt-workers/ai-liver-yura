from datetime import datetime, timezone

import pytest

from app.domain.contracts import CapabilityAvailability, CapabilityRequirement
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


def manifest(*, plugin_id: str = "plugin-a", capability_id: str = "capability-a") -> PluginManifest:
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


def grants(revision: int, plugin_id: str = "plugin-a") -> PluginPermissionGrantSnapshot:
    return PluginPermissionGrantSnapshot(
        revision, (PluginPermissionGrant(plugin_id, permission()),), NOW
    )


def health(
    plugin_id: str, generation: int, revision: int, state: PluginHealthState
) -> PluginHealthObservation:
    return PluginHealthObservation(
        plugin_id,
        generation,
        revision,
        state,
        (PluginCapabilityHealth("capability-a", state),),
        NOW,
    )


def test_permission_health_and_foundation_projection() -> None:
    registry = PluginRegistryAuthority()
    registry.register_manifest(manifest(), NOW)
    registry.adopt_permission_grants(grants(0))
    snapshot = registry.apply_health_observation(
        health("plugin-a", 0, 0, PluginHealthState.HEALTHY)
    )
    assert snapshot.plugins[0].lifecycle_state is PluginLifecycleState.AVAILABLE
    descriptor = snapshot.foundation_capabilities[0]
    assert descriptor.availability is CapabilityAvailability.AVAILABLE
    assert descriptor.satisfies(CapabilityRequirement("plugin", "execute"))


def test_cross_plugin_grant_does_not_authorize() -> None:
    registry = PluginRegistryAuthority()
    registry.register_manifest(manifest(plugin_id="plugin-b", capability_id="capability-b"), NOW)
    registry.adopt_permission_grants(grants(0, "plugin-a"))
    snapshot = registry.snapshot(NOW)
    assert snapshot.foundation_capabilities == ()
    assert snapshot.capabilities[0].effective_availability is CapabilityAvailability.UNAVAILABLE


def test_stop_unregister_readd_keeps_descriptor_revision_floor() -> None:
    registry = PluginRegistryAuthority()
    registry.register_manifest(manifest(), NOW)
    registry.adopt_permission_grants(grants(0))
    registry.apply_health_observation(health("plugin-a", 0, 0, PluginHealthState.HEALTHY))
    first = registry.snapshot(NOW).foundation_capabilities[0].revision
    registry.begin_stop("plugin-a", NOW)
    registry.mark_stopped("plugin-a", NOW)
    registry.unregister("plugin-a", NOW)
    registry.register_manifest(manifest(), NOW)
    registry.adopt_permission_grants(grants(1))
    registry.apply_health_observation(health("plugin-a", 1, 0, PluginHealthState.HEALTHY))
    assert registry.snapshot(NOW).foundation_capabilities[0].revision > first


def test_stale_or_conflicting_grant_snapshot_rejects() -> None:
    registry = PluginRegistryAuthority()
    registry.adopt_permission_grants(grants(1))
    with pytest.raises(ValueError):
        registry.adopt_permission_grants(grants(0))
    with pytest.raises(ValueError):
        registry.adopt_permission_grants(PluginPermissionGrantSnapshot(1, (), NOW))


def test_stop_fence_wins_over_late_healthy_observation() -> None:
    registry = PluginRegistryAuthority()
    registry.register_manifest(manifest(), NOW)
    registry.adopt_permission_grants(grants(0))
    registry.apply_health_observation(health("plugin-a", 0, 0, PluginHealthState.HEALTHY))
    registry.begin_stop("plugin-a", NOW)
    snapshot = registry.apply_health_observation(
        health("plugin-a", 0, 1, PluginHealthState.HEALTHY)
    )
    assert snapshot.plugins[0].lifecycle_state is PluginLifecycleState.STOPPING
    assert snapshot.foundation_capabilities[0].availability is CapabilityAvailability.UNAVAILABLE


def test_scope_is_exact_and_old_generation_health_is_rejected() -> None:
    registry = PluginRegistryAuthority()
    registry.register_manifest(manifest(), NOW)
    wrong_scope = PluginPermissionGrantSnapshot(
        0,
        (PluginPermissionGrant("plugin-a", PluginPermissionRef("network_access", "scope-b")),),
        NOW,
    )
    registry.adopt_permission_grants(wrong_scope)
    assert registry.snapshot(NOW).foundation_capabilities == ()
    registry.begin_stop("plugin-a", NOW)
    registry.mark_stopped("plugin-a", NOW)
    registry.unregister("plugin-a", NOW)
    registry.register_manifest(manifest(), NOW)
    with pytest.raises(ValueError):
        registry.apply_health_observation(health("plugin-a", 0, 1, PluginHealthState.HEALTHY))
