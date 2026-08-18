from datetime import datetime, timedelta, timezone

from app.domain.activity_execution import (
    ActivityExecutionAuthority,
    ActivityInterruptibility,
    ActivityInvocation,
    ExecutionAdapterReport,
    ExecutionEffectEvidence,
    ExecutionEffectKind,
    ExecutionPreflightSnapshot,
)
from app.domain.contracts import (
    AuthorityRef,
    CapabilityRequirement,
    ExecutionStatus,
    IntentKind,
    IntentRef,
    RevisionVector,
    SystemCommand,
)
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
REVISIONS = RevisionVector(7, 5, 3)
DISPATCH_ID = "command-plugin:invocation-plugin"


def permission(permission_id: str) -> PluginPermissionRef:
    return PluginPermissionRef(permission_id, "scope-a")


def operation(
    operation_id: str,
    required_permission: PluginPermissionRef,
) -> PluginOperationDeclaration:
    return PluginOperationDeclaration(
        operation_id,
        f"plugin.{operation_id}.input.v1",
        f"plugin.{operation_id}.output.v1",
        PluginSideEffectClass.OBSERVABLE_EXTERNAL,
        (required_permission,),
        PluginCancellationSupport.SOFT,
        PluginTimeoutSupport(True, True),
    )


def plugin_manifest() -> PluginManifest:
    run = permission("run_permission")
    inspect = permission("inspect_permission")
    return PluginManifest(
        "plugin-a",
        "1.0.0",
        1,
        "Plugin",
        (
            PluginCapabilityDeclaration(
                "capability-a",
                "activity",
                (
                    operation("run", run),
                    operation("inspect", inspect),
                ),
            ),
        ),
    )


def grant_snapshot(
    revision: int,
    permissions: tuple[PluginPermissionRef, ...],
) -> PluginPermissionGrantSnapshot:
    return PluginPermissionGrantSnapshot(
        revision,
        tuple(PluginPermissionGrant("plugin-a", item) for item in permissions),
        NOW + timedelta(seconds=revision),
    )


def healthy_observation() -> PluginHealthObservation:
    return PluginHealthObservation(
        "plugin-a",
        0,
        0,
        PluginHealthState.HEALTHY,
        (PluginCapabilityHealth("capability-a", PluginHealthState.HEALTHY),),
        NOW,
    )


def available_registry() -> PluginRegistryAuthority:
    registry = PluginRegistryAuthority()
    registry.register_manifest(plugin_manifest(), NOW)
    registry.adopt_permission_grants(
        grant_snapshot(
            0,
            (
                permission("run_permission"),
                permission("inspect_permission"),
            ),
        )
    )
    registry.apply_health_observation(healthy_observation())
    return registry


def command() -> SystemCommand:
    return SystemCommand(
        "command-plugin",
        "decision-plugin",
        IntentRef(IntentKind.ACTIVITY, "intent-plugin"),
        AuthorityRef("executive", "conscious_goal_action", "decision-plugin"),
        NOW,
        REVISIONS,
        None,
        (),
        (CapabilityRequirement("activity", "run"),),
    )


def invocation() -> ActivityInvocation:
    return ActivityInvocation(
        "invocation-plugin",
        command(),
        "activity.run",
        {},
        ActivityInterruptibility.INTERRUPTIBLE,
        NOW,
    )


def preflight(registry: PluginRegistryAuthority) -> ExecutionPreflightSnapshot:
    return ExecutionPreflightSnapshot(
        REVISIONS,
        registry.snapshot(NOW).foundation_capabilities,
        (),
        NOW,
    )


def test_old_activity_binding_is_rejected_after_plugin_descriptor_change() -> None:
    registry = available_registry()
    first_descriptor = registry.snapshot(NOW).foundation_capabilities[0]
    activity = ActivityExecutionAuthority()
    admitted = activity.admit(invocation(), preflight(registry))
    assert admitted.bindings[0].descriptor_revision == first_descriptor.revision

    registry.adopt_permission_grants(
        grant_snapshot(
            1,
            (permission("run_permission"),),
        )
    )
    current_descriptor = registry.snapshot(NOW).foundation_capabilities[0]
    assert current_descriptor.operations == ("run",)
    assert current_descriptor.revision > first_descriptor.revision

    started = activity.start(
        "command-plugin",
        preflight(registry),
        NOW + timedelta(seconds=2),
        DISPATCH_ID,
    )
    assert started.result.status is ExecutionStatus.SUPERSEDED


def test_plugin_removal_does_not_erase_activity_execution_effect_history() -> None:
    registry = available_registry()
    activity = ActivityExecutionAuthority()
    activity.admit(invocation(), preflight(registry))
    activity.start(
        "command-plugin",
        preflight(registry),
        NOW + timedelta(seconds=1),
        DISPATCH_ID,
    )
    activity.apply_report(
        ExecutionAdapterReport(
            "command-plugin",
            "invocation-plugin",
            DISPATCH_ID,
            ExecutionStatus.APPLIED,
            NOW + timedelta(seconds=2),
            {},
            (
                ExecutionEffectEvidence(
                    "effect-plugin",
                    "capability-a",
                    registry.snapshot(NOW).foundation_capabilities[0].revision,
                    "activity.run",
                    ExecutionEffectKind.APPLIED,
                    {"evidence": "adapter"},
                ),
            ),
        )
    )

    registry.begin_stop("plugin-a", NOW + timedelta(seconds=3))
    registry.mark_stopped("plugin-a", NOW + timedelta(seconds=4))
    registry.unregister("plugin-a", NOW + timedelta(seconds=5))

    recorded = activity.snapshot("command-plugin")
    assert recorded is not None
    assert recorded.result.effect_refs == ("effect-plugin",)
    assert registry.snapshot(NOW).foundation_capabilities == ()
