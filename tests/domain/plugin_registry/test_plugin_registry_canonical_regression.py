import inspect
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.contracts import CapabilityAvailability, CapabilityRequirement, ExecutionResult
from app.domain.plugin_registry import (
    PluginCancellationSupport,
    PluginCapabilityDeclaration,
    PluginCapabilityHealth,
    PluginHealthObservation,
    PluginHealthState,
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


def permission(
    permission_id: str = "network_access",
    scope_ref: str | None = "scope-a",
) -> PluginPermissionRef:
    return PluginPermissionRef(permission_id, scope_ref)


def operation(
    required_permissions: tuple[PluginPermissionRef, ...] | None = None,
) -> PluginOperationDeclaration:
    return PluginOperationDeclaration(
        "execute",
        "plugin.input.v1",
        "plugin.output.v1",
        PluginSideEffectClass.OBSERVABLE_EXTERNAL,
        (permission(),) if required_permissions is None else required_permissions,
        PluginCancellationSupport.SOFT,
        PluginTimeoutSupport(True, True),
    )


def manifest(
    *,
    plugin_version: str = "1.0.0",
    required_permissions: tuple[PluginPermissionRef, ...] | None = None,
) -> PluginManifest:
    operation_permissions = (
        (permission(),) if required_permissions is None else required_permissions
    )
    return PluginManifest(
        "plugin-a",
        plugin_version,
        1,
        "Plugin",
        (
            PluginCapabilityDeclaration(
                "capability-a",
                "plugin",
                (operation(operation_permissions),),
            ),
        ),
    )


def grants(
    revision: int,
    permissions: tuple[PluginPermissionRef, ...] | None = None,
    *,
    captured_at: datetime = NOW,
) -> PluginPermissionGrantSnapshot:
    selected = (permission(),) if permissions is None else permissions
    return PluginPermissionGrantSnapshot(
        revision,
        tuple(PluginPermissionGrant("plugin-a", item) for item in selected),
        captured_at,
    )


def health(
    *,
    generation: int = 0,
    revision: int = 0,
    state: PluginHealthState = PluginHealthState.HEALTHY,
    observed_at: datetime = NOW,
) -> PluginHealthObservation:
    return PluginHealthObservation(
        "plugin-a",
        generation,
        revision,
        state,
        (PluginCapabilityHealth("capability-a", state),),
        observed_at,
    )


def available_registry() -> PluginRegistryAuthority:
    registry = PluginRegistryAuthority()
    registry.register_manifest(manifest(), NOW)
    registry.adopt_permission_grants(grants(0))
    registry.apply_health_observation(health())
    return registry


def test_invalid_permission_ref_and_boolean_revisions_are_rejected() -> None:
    with pytest.raises(ValueError, match="permission_id"):
        PluginPermissionRef("", "scope-a")
    with pytest.raises(ValueError, match="grant_revision"):
        PluginPermissionGrantSnapshot(True, (), NOW)
    with pytest.raises(ValueError, match="plugin_generation"):
        PluginHealthObservation(
            "plugin-a",
            True,
            0,
            PluginHealthState.HEALTHY,
            (),
            NOW,
        )


def test_grant_revision_rollback_and_conflict_are_fail_closed() -> None:
    registry = PluginRegistryAuthority()
    registry.register_manifest(manifest(), NOW)
    registry.adopt_permission_grants(grants(1))
    before = registry.snapshot(NOW)

    with pytest.raises(ValueError, match="stale"):
        registry.adopt_permission_grants(grants(0))
    with pytest.raises(ValueError, match="payload"):
        registry.adopt_permission_grants(grants(1, ()))

    after = registry.snapshot(NOW)
    assert after.registry_revision == before.registry_revision
    assert after.plugins == before.plugins
    assert after.capabilities == before.capabilities


def test_missing_one_permission_and_pattern_like_grants_do_not_authorize() -> None:
    first = PluginPermissionRef("network_access", "scope-a")
    second = PluginPermissionRef("filesystem_read", "scope-a")
    registry = PluginRegistryAuthority()
    registry.register_manifest(
        manifest(required_permissions=(first, second)),
        NOW,
    )

    registry.adopt_permission_grants(grants(0, (first,)))
    assert registry.snapshot(NOW).foundation_capabilities == ()

    registry.adopt_permission_grants(
        grants(
            1,
            (
                first,
                PluginPermissionRef("filesystem_*", "scope-a"),
            ),
        )
    )
    assert registry.snapshot(NOW).foundation_capabilities == ()

    registry.adopt_permission_grants(grants(2, (first, second)))
    assert len(registry.snapshot(NOW).foundation_capabilities) == 1


def test_health_observation_noop_does_not_advance_registry_revision() -> None:
    registry = available_registry()
    before = registry.snapshot(NOW)

    registry.apply_health_observation(health(revision=1, observed_at=LATER))
    after = registry.snapshot(LATER)

    assert after.registry_revision == before.registry_revision
    assert after.plugins == before.plugins
    assert after.capabilities == before.capabilities


def test_unknown_and_unavailable_descriptors_do_not_satisfy_requirement() -> None:
    requirement = CapabilityRequirement("plugin", "execute")
    registry = PluginRegistryAuthority()
    registry.register_manifest(manifest(), NOW)
    registry.adopt_permission_grants(grants(0))

    unknown = registry.snapshot(NOW).foundation_capabilities[0]
    assert unknown.availability is CapabilityAvailability.UNKNOWN
    assert not unknown.satisfies(requirement)

    unavailable = registry.apply_health_observation(
        health(state=PluginHealthState.UNAVAILABLE)
    ).foundation_capabilities[0]
    assert unavailable.availability is CapabilityAvailability.UNAVAILABLE
    assert not unavailable.satisfies(requirement)


def test_readd_metadata_change_advances_descriptor_revision_above_tombstone() -> None:
    registry = available_registry()
    before = registry.snapshot(NOW).foundation_capabilities[0]
    registry.begin_stop("plugin-a", NOW)
    registry.mark_stopped("plugin-a", NOW)
    registry.unregister("plugin-a", NOW)

    registry.register_manifest(manifest(plugin_version="2.0.0"), LATER)
    registry.adopt_permission_grants(grants(1, captured_at=LATER))
    registry.apply_health_observation(
        health(generation=1, observed_at=LATER)
    )

    after = registry.snapshot(LATER).foundation_capabilities[0]
    assert after.revision > before.revision
    assert isinstance(after.attributes, Mapping)
    assert after.attributes["plugin_version"] == "2.0.0"


def test_registry_public_api_has_no_core_authority_or_raw_text_mutation_inputs() -> None:
    forbidden = {
        "goal",
        "internal_state",
        "character",
        "body",
        "raw_user_text",
        "execution_result",
        "actual_effect",
    }
    for method_name in (
        "discover",
        "validate",
        "register",
        "register_manifest",
        "adopt_permission_grants",
        "apply_health_observation",
        "begin_stop",
        "mark_stopped",
        "unregister",
    ):
        signature = inspect.signature(getattr(PluginRegistryAuthority, method_name))
        assert set(signature.parameters).isdisjoint(forbidden)


def test_registry_mutations_never_return_execution_result_authority() -> None:
    registry = PluginRegistryAuthority()
    registered = registry.register_manifest(manifest(), NOW)
    permission_snapshot = registry.adopt_permission_grants(grants(0))
    health_snapshot = registry.apply_health_observation(health())

    assert not isinstance(registered, ExecutionResult)
    assert not isinstance(permission_snapshot, ExecutionResult)
    assert not isinstance(health_snapshot, ExecutionResult)
