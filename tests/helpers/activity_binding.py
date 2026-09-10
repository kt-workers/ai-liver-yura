"""試験で指定する操作と引数を正規Registry・binding公開へ登録する。"""

from dataclasses import replace
from datetime import datetime, timezone
from functools import lru_cache

from app.domain.activity_binding import (
    ActivityBindingAuthority,
    ActivityExecutionBindingPublication,
    ArgumentKind,
    ArgumentSourceFact,
    ArgumentSourceOwner,
    ArgumentSourceRelation,
    BindingInputPublicationOwner,
    OperationInputContract,
)
from app.domain.plugin_registry.activity_binding import PluginActivityOperationAdapter
from app.domain.plugin_registry.authority import PluginRegistryAuthority
from app.domain.plugin_registry.contracts import (
    PluginCancellationSupport,
    PluginCapabilityDeclaration,
    PluginCapabilityHealth,
    PluginHealthObservation,
    PluginHealthState,
    PluginManifest,
    PluginOperationDeclaration,
    PluginSideEffectClass,
    PluginTimeoutSupport,
)


@lru_cache(maxsize=128)
def planning_binding(
    operation: str = "collect",
    activity_type: str = "research",
    capability_id: str = "cap-research",
    operations: tuple[str, ...] = (),
) -> ActivityExecutionBindingPublication:
    now = datetime(2026, 8, 15, tzinfo=timezone.utc)
    registry = PluginRegistryAuthority()
    op = PluginOperationDeclaration(
        operation,
        "test-input",
        "test-output",
        PluginSideEffectClass.NONE,
        (),
        PluginCancellationSupport.SOFT,
        PluginTimeoutSupport(True, True),
    )
    registry.register_manifest(
        PluginManifest(
            "test",
            "1",
            1,
            "試験",
            (
                PluginCapabilityDeclaration(
                    capability_id,
                    activity_type,
                    tuple(replace(op, operation_id=name) for name in (operations or (operation,))),
                ),
            ),
        ),
        now,
    )
    registry.apply_health_observation(
        PluginHealthObservation(
            "test",
            0,
            0,
            PluginHealthState.HEALTHY,
            (PluginCapabilityHealth(capability_id, PluginHealthState.HEALTHY),),
            now,
        )
    )
    schema = BindingInputPublicationOwner(
        "test-schema", OperationInputContract("test-input", 1, (("query", ArgumentKind.STRING),))
    )
    source = ArgumentSourceOwner(
        "test-source", (ArgumentSourceFact("goal-1", "test-source", 1, "test-input", "資料"),)
    )
    owner = ActivityBindingAuthority(
        "binding-" + activity_type + "-" + operation,
        PluginActivityOperationAdapter(registry),
        schema,
        (source,),
    )
    return owner.publish(
        revision=1,
        activity_type=activity_type,
        operation_ref=operation,
        target_ref="target-1",
        capability_id=capability_id,
        relations=(ArgumentSourceRelation("query", "goal-1"),),
    )
