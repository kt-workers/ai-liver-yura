from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.contracts import CapabilityAvailability, CapabilityRequirement
from app.domain.plugin_registry import (
    PluginCancellationSupport,
    PluginCapabilityDeclaration,
    PluginCapabilityHealth,
    PluginDependencyRef,
    PluginHealthObservation,
    PluginHealthState,
    PluginLifecycleState,
    PluginManifest,
    PluginOperationDeclaration,
    PluginPermissionGrant,
    PluginPermissionGrantSnapshot,
    PluginPermissionRef,
    PluginRegistryAuthority,
    PluginRegistryRevisionStaleError,
    PluginResourceRequirement,
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
    operation_id: str = "execute",
    *,
    required_permissions: tuple[PluginPermissionRef, ...] | None = None,
) -> PluginOperationDeclaration:
    return PluginOperationDeclaration(
        operation_id,
        "plugin.input.v1",
        "plugin.output.v1",
        PluginSideEffectClass.OBSERVABLE_EXTERNAL,
        (permission(),) if required_permissions is None else required_permissions,
        PluginCancellationSupport.SOFT,
        PluginTimeoutSupport(True, True),
    )


def capability(
    capability_id: str = "capability-a",
    *,
    capability_type: str = "plugin",
    operations: tuple[PluginOperationDeclaration, ...] | None = None,
    required_permissions: tuple[PluginPermissionRef, ...] = (),
) -> PluginCapabilityDeclaration:
    return PluginCapabilityDeclaration(
        capability_id,
        capability_type,
        (operation(),) if operations is None else operations,
        required_permissions,
    )


def manifest(
    *,
    plugin_id: str = "plugin-a",
    capabilities: tuple[PluginCapabilityDeclaration, ...] | None = None,
    contract_version: int = 1,
    required_permissions: tuple[PluginPermissionRef, ...] = (),
    optional_dependencies: tuple[PluginDependencyRef, ...] = (),
    resource_requirements: tuple[PluginResourceRequirement, ...] = (),
) -> PluginManifest:
    return PluginManifest(
        plugin_id,
        "1.0.0",
        contract_version,
        "Plugin",
        (capability(),) if capabilities is None else capabilities,
        required_permissions,
        optional_dependencies,
        resource_requirements,
    )


def grants(
    revision: int,
    *,
    plugin_id: str = "plugin-a",
    permissions: tuple[PluginPermissionRef, ...] | None = None,
    captured_at: datetime = NOW,
) -> PluginPermissionGrantSnapshot:
    selected = (permission(),) if permissions is None else permissions
    return PluginPermissionGrantSnapshot(
        revision,
        tuple(PluginPermissionGrant(plugin_id, item) for item in selected),
        captured_at,
    )


def health(
    *,
    plugin_id: str = "plugin-a",
    capability_id: str = "capability-a",
    generation: int = 0,
    revision: int = 0,
    plugin_state: PluginHealthState = PluginHealthState.HEALTHY,
    capability_state: PluginHealthState | None = None,
    observed_at: datetime = NOW,
) -> PluginHealthObservation:
    return PluginHealthObservation(
        plugin_id,
        generation,
        revision,
        plugin_state,
        (
            PluginCapabilityHealth(
                capability_id,
                plugin_state if capability_state is None else capability_state,
            ),
        ),
        observed_at,
    )


def available_registry() -> PluginRegistryAuthority:
    registry = PluginRegistryAuthority()
    registry.register_manifest(manifest(), NOW)
    registry.adopt_permission_grants(grants(0))
    registry.apply_health_observation(health())
    return registry


def test_manifest_is_strict_and_owns_mutable_caller_collections() -> None:
    capabilities = [capability()]
    value = manifest(capabilities=capabilities)  # type: ignore[arg-type]
    capabilities.append(capability("capability-b"))
    assert tuple(item.capability_id for item in value.capabilities) == ("capability-a",)

    with pytest.raises(ValueError, match="contract_version"):
        manifest(contract_version=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="未対応"):
        manifest(contract_version=2)
    with pytest.raises(ValueError, match="自分自身"):
        manifest(optional_dependencies=(PluginDependencyRef("plugin-a"),))
    with pytest.raises(ValueError):
        manifest(resource_requirements=(PluginResourceRequirement("gpu", -1, "unit"),))


def test_duplicate_capability_and_operation_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="capabilities"):
        manifest(capabilities=(capability("same"), capability("same")))
    with pytest.raises(ValueError, match="operations"):
        capability(
            operations=(
                operation("same"),
                operation("same", required_permissions=()),
            )
        )


def test_permission_identity_is_exact_pair_at_all_declaration_levels() -> None:
    scope_a = permission(scope_ref="scope-a")
    scope_b = permission(scope_ref="scope-b")

    op = operation(required_permissions=(scope_a, scope_b))
    cap = capability(
        operations=(op,),
        required_permissions=(scope_a, scope_b),
    )
    value = manifest(
        capabilities=(cap,),
        required_permissions=(scope_a, scope_b),
    )
    assert value.capabilities[0].operations[0].required_permissions == (scope_a, scope_b)

    with pytest.raises(ValueError, match="required_permissions"):
        operation(required_permissions=(scope_a, scope_a))
    with pytest.raises(ValueError, match="required_permissions"):
        capability(required_permissions=(scope_a, scope_a))
    with pytest.raises(ValueError, match="required_permissions"):
        manifest(required_permissions=(scope_a, scope_a))


def test_first_registration_duplicate_and_collision_are_atomic() -> None:
    registry = PluginRegistryAuthority()
    registry.register_manifest(manifest(), NOW, expected_registry_revision=0)
    assert registry.snapshot(NOW).registry_revision == 1

    before = registry.snapshot(NOW)
    with pytest.raises(ValueError, match="すでにactive"):
        registry.register_manifest(
            manifest(),
            NOW,
            expected_registry_revision=before.registry_revision,
        )
    assert registry.snapshot(NOW).registry_revision == before.registry_revision

    with pytest.raises(ValueError, match="衝突"):
        registry.register_manifest(
            manifest(plugin_id="plugin-b"),
            NOW,
            expected_registry_revision=before.registry_revision,
        )
    after = registry.snapshot(NOW)
    assert after.registry_revision == before.registry_revision
    assert tuple(item.manifest.plugin_id for item in after.plugins) == ("plugin-a",)


def test_multi_capability_registration_is_all_or_nothing() -> None:
    registry = PluginRegistryAuthority()
    registry.register_manifest(manifest(), NOW)
    before = registry.snapshot(NOW)
    candidate = manifest(
        plugin_id="plugin-b",
        capabilities=(
            capability("capability-a"),
            capability("capability-b"),
        ),
    )
    with pytest.raises(ValueError, match="衝突"):
        registry.register_manifest(
            candidate,
            NOW,
            expected_registry_revision=before.registry_revision,
        )
    after = registry.snapshot(NOW)
    assert after.registry_revision == before.registry_revision
    assert tuple(item.declaration.capability_id for item in after.capabilities) == (
        "capability-a",
    )
    assert all(item.manifest.plugin_id != "plugin-b" for item in after.plugins)


def test_overlapping_type_and_operation_with_unique_capability_ids_is_allowed() -> None:
    registry = PluginRegistryAuthority()
    registry.register_manifest(
        manifest(
            capabilities=(
                capability("capability-a"),
                capability("capability-b"),
            )
        ),
        NOW,
    )
    assert tuple(
        item.declaration.capability_id for item in registry.snapshot(NOW).capabilities
    ) == ("capability-a", "capability-b")


def test_permission_exact_match_scope_and_cross_plugin_isolation() -> None:
    registry = PluginRegistryAuthority()
    registry.register_manifest(manifest(), NOW)

    registry.adopt_permission_grants(
        grants(0, permissions=(permission(scope_ref="scope-b"),))
    )
    assert registry.snapshot(NOW).foundation_capabilities == ()

    registry.adopt_permission_grants(
        grants(
            1,
            permissions=(PluginPermissionRef("network", "scope-a"),),
        )
    )
    assert registry.snapshot(NOW).foundation_capabilities == ()

    registry.adopt_permission_grants(
        grants(2, plugin_id="plugin-b")
    )
    assert registry.snapshot(NOW).foundation_capabilities == ()

    registry.adopt_permission_grants(grants(3))
    assert len(registry.snapshot(NOW).foundation_capabilities) == 1


def test_same_permission_id_with_distinct_scopes_can_both_be_granted() -> None:
    scope_a = permission(scope_ref="scope-a")
    scope_b = permission(scope_ref="scope-b")
    registry = PluginRegistryAuthority()
    registry.register_manifest(
        manifest(
            capabilities=(
                capability(
                    operations=(
                        operation(required_permissions=(scope_a, scope_b)),
                    )
                ),
            )
        ),
        NOW,
    )
    registry.adopt_permission_grants(
        grants(0, permissions=(scope_a, scope_b))
    )
    registry.apply_health_observation(health())
    descriptor = registry.snapshot(NOW).foundation_capabilities[0]
    assert descriptor.availability is CapabilityAvailability.AVAILABLE


def test_permission_refresh_and_revocation_are_monotonic_but_noop_is_not() -> None:
    registry = PluginRegistryAuthority()
    registry.register_manifest(manifest(), NOW)
    registered = registry.snapshot(NOW)

    registry.adopt_permission_grants(
        grants(0),
        expected_registry_revision=registered.registry_revision,
    )
    granted = registry.snapshot(NOW)
    granted_descriptor = granted.foundation_capabilities[0]

    registry.adopt_permission_grants(
        grants(0),
        expected_registry_revision=granted.registry_revision,
    )
    assert registry.snapshot(NOW).registry_revision == granted.registry_revision

    registry.adopt_permission_grants(
        grants(1, permissions=()),
        expected_registry_revision=granted.registry_revision,
    )
    revoked = registry.snapshot(NOW)
    assert revoked.registry_revision == granted.registry_revision + 1
    assert revoked.foundation_capabilities == ()
    assert revoked.capabilities[0].capability_revision > granted_descriptor.revision


def test_plugin_health_cannot_override_missing_permission() -> None:
    registry = PluginRegistryAuthority()
    registry.register_manifest(manifest(), NOW)
    snapshot = registry.apply_health_observation(health())
    assert snapshot.foundation_capabilities == ()
    assert snapshot.capabilities[0].effective_availability is CapabilityAvailability.UNAVAILABLE


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (PluginHealthState.HEALTHY, CapabilityAvailability.AVAILABLE),
        (PluginHealthState.DEGRADED, CapabilityAvailability.DEGRADED),
        (PluginHealthState.UNAVAILABLE, CapabilityAvailability.UNAVAILABLE),
        (PluginHealthState.UNKNOWN, CapabilityAvailability.UNKNOWN),
    ],
)
def test_health_projection_is_closed(
    state: PluginHealthState,
    expected: CapabilityAvailability,
) -> None:
    registry = PluginRegistryAuthority()
    registry.register_manifest(manifest(), NOW)
    registry.adopt_permission_grants(grants(0))
    snapshot = registry.apply_health_observation(
        health(plugin_state=state, capability_state=state)
    )
    assert snapshot.foundation_capabilities[0].availability is expected


def test_capability_health_override_and_health_revision_validation() -> None:
    registry = PluginRegistryAuthority()
    registry.register_manifest(manifest(), NOW)
    registry.adopt_permission_grants(grants(0))
    degraded = registry.apply_health_observation(
        health(
            plugin_state=PluginHealthState.HEALTHY,
            capability_state=PluginHealthState.DEGRADED,
        )
    )
    assert degraded.foundation_capabilities[0].availability is CapabilityAvailability.DEGRADED

    with pytest.raises(ValueError, match="revision"):
        registry.apply_health_observation(
            health(
                revision=-1,
                observed_at=LATER,
            )
        )

    with pytest.raises(ValueError, match="payload"):
        registry.apply_health_observation(
            health(
                revision=0,
                plugin_state=PluginHealthState.UNAVAILABLE,
                observed_at=NOW,
            )
        )

    with pytest.raises(ValueError, match="巻き戻"):
        registry.apply_health_observation(
            health(
                revision=1,
                observed_at=NOW - timedelta(seconds=1),
            )
        )


def test_unknown_capability_health_is_rejected() -> None:
    registry = PluginRegistryAuthority()
    registry.register_manifest(manifest(), NOW)
    observation = health(capability_id="unknown-capability")
    with pytest.raises(ValueError, match="未知capability"):
        registry.apply_health_observation(observation)


def test_lifecycle_accepted_visible_mutations_advance_registry_revision_once() -> None:
    registry = PluginRegistryAuthority()
    assert registry.snapshot(NOW).registry_revision == 0

    registry.discover(manifest(), NOW, expected_registry_revision=0)
    assert registry.snapshot(NOW).registry_revision == 1

    registry.validate("plugin-a", NOW, expected_registry_revision=1)
    assert registry.snapshot(NOW).registry_revision == 2

    registry.register("plugin-a", NOW, expected_registry_revision=2)
    assert registry.snapshot(NOW).registry_revision == 3

    registry.begin_stop("plugin-a", NOW, expected_registry_revision=3)
    assert registry.snapshot(NOW).registry_revision == 4

    registry.mark_stopped("plugin-a", NOW, expected_registry_revision=4)
    assert registry.snapshot(NOW).registry_revision == 5

    registry.unregister("plugin-a", NOW, expected_registry_revision=5)
    assert registry.snapshot(NOW).registry_revision == 6


def test_illegal_lifecycle_transition_does_not_advance_revision() -> None:
    registry = PluginRegistryAuthority()
    registry.discover(manifest(), NOW)
    before = registry.snapshot(NOW)
    with pytest.raises(ValueError, match="transition"):
        registry.register("plugin-a", NOW, expected_registry_revision=before.registry_revision)
    assert registry.snapshot(NOW).registry_revision == before.registry_revision


def test_stop_fence_wins_over_late_healthy_observation() -> None:
    registry = available_registry()
    before = registry.snapshot(NOW).registry_revision
    registry.begin_stop("plugin-a", NOW, expected_registry_revision=before)
    stopping = registry.snapshot(NOW)
    late = registry.apply_health_observation(
        health(revision=1, observed_at=LATER)
    )
    assert late.registry_revision == stopping.registry_revision
    assert late.plugins[0].lifecycle_state is PluginLifecycleState.STOPPING
    assert late.foundation_capabilities[0].availability is CapabilityAvailability.UNAVAILABLE


def test_unregister_readd_uses_new_generation_and_tombstone_floor() -> None:
    registry = available_registry()
    first = registry.snapshot(NOW)
    old_revision = first.foundation_capabilities[0].revision

    registry.begin_stop("plugin-a", NOW)
    registry.mark_stopped("plugin-a", NOW)
    registry.unregister("plugin-a", NOW)
    registry.register_manifest(manifest(), NOW)
    registry.adopt_permission_grants(grants(1))
    registry.apply_health_observation(health(generation=1))

    current = registry.snapshot(NOW)
    assert current.plugins[0].plugin_generation == 1
    assert current.foundation_capabilities[0].revision > old_revision

    with pytest.raises(ValueError, match="generation"):
        registry.apply_health_observation(
            health(generation=0, revision=2, observed_at=LATER)
        )


def test_expected_registry_revision_is_fail_closed_and_typed() -> None:
    registry = PluginRegistryAuthority()
    registry.register_manifest(
        manifest(),
        NOW,
        expected_registry_revision=0,
    )
    before = registry.snapshot(NOW)

    with pytest.raises(PluginRegistryRevisionStaleError) as caught:
        registry.begin_stop(
            "plugin-a",
            NOW,
            expected_registry_revision=0,
        )
    assert caught.value.code == "REGISTRY_REVISION_STALE"
    assert caught.value.expected_registry_revision == 0
    assert caught.value.current_registry_revision == before.registry_revision
    assert registry.snapshot(NOW) == before

    with pytest.raises(ValueError, match="expected_registry_revision"):
        registry.begin_stop(
            "plugin-a",
            NOW,
            expected_registry_revision=True,  # type: ignore[arg-type]
        )


def test_same_expected_revision_concurrent_mutation_has_at_most_one_success() -> None:
    registry = PluginRegistryAuthority()

    def attempt(index: int) -> str:
        try:
            registry.register_manifest(
                manifest(
                    plugin_id=f"plugin-{index}",
                    capabilities=(capability(f"capability-{index}"),),
                ),
                NOW,
                expected_registry_revision=0,
            )
            return "accepted"
        except PluginRegistryRevisionStaleError:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(attempt, (1, 2)))

    assert outcomes.count("accepted") == 1
    assert outcomes.count("stale") == 1
    assert registry.snapshot(NOW).registry_revision == 1


def test_foundation_projection_is_deterministic_closed_and_requirement_compatible() -> None:
    registry = PluginRegistryAuthority()
    registry.register_manifest(
        manifest(
            capabilities=(
                capability("capability-b"),
                capability("capability-a"),
            )
        ),
        NOW,
    )
    registry.adopt_permission_grants(grants(0))
    registry.apply_health_observation(
        PluginHealthObservation(
            "plugin-a",
            0,
            0,
            PluginHealthState.HEALTHY,
            (
                PluginCapabilityHealth("capability-b", PluginHealthState.HEALTHY),
                PluginCapabilityHealth("capability-a", PluginHealthState.HEALTHY),
            ),
            NOW,
        )
    )
    snapshot = registry.snapshot(NOW)
    assert tuple(item.capability_id for item in snapshot.foundation_capabilities) == (
        "capability-a",
        "capability-b",
    )
    descriptor = snapshot.foundation_capabilities[0]
    assert descriptor.satisfies(CapabilityRequirement("plugin", "execute"))
    assert set(descriptor.attributes) == {
        "schema_id",
        "plugin_id",
        "plugin_generation",
        "plugin_version",
        "contract_version",
        "operations",
        "required_permissions",
    }
    rendered = repr(descriptor.attributes)
    assert "credential" not in rendered
    assert "token" not in rendered
    assert "raw user" not in rendered


def test_degraded_requirement_semantics_match_foundation_contract() -> None:
    registry = PluginRegistryAuthority()
    registry.register_manifest(manifest(), NOW)
    registry.adopt_permission_grants(grants(0))
    descriptor = registry.apply_health_observation(
        health(plugin_state=PluginHealthState.DEGRADED)
    ).foundation_capabilities[0]
    assert not descriptor.satisfies(CapabilityRequirement("plugin", "execute"))
    assert descriptor.satisfies(CapabilityRequirement("plugin", "execute", True))


def test_registry_rejects_non_manifest_and_never_executes_manifest_data() -> None:
    registry = PluginRegistryAuthority()
    with pytest.raises(ValueError, match="manifest"):
        registry.register_manifest(object(), NOW)  # type: ignore[arg-type]

    suspicious = manifest(plugin_id="module.import.shell")
    registry.register_manifest(suspicious, NOW)
    assert registry.snapshot(NOW).plugins[0].manifest.plugin_id == "module.import.shell"
