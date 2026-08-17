from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from threading import RLock

from app.domain.contracts import CapabilityAvailability, CapabilityDescriptor
from app.domain.contracts.common import require_aware, require_revision, utc_instant

from .contracts import (
    PluginCapabilityDeclaration,
    PluginHealthObservation,
    PluginHealthState,
    PluginLifecycleState,
    PluginManifest,
    PluginPermissionGrantSnapshot,
    PluginPermissionRef,
    PluginRegistrySnapshot,
    RegisteredCapabilityView,
    RegisteredPluginView,
)
from .projector import project_capability


class PluginRegistryRevisionStaleError(ValueError):
    """callerが参照したRegistry revisionとcurrent stateが一致しないtyped conflict。"""

    code = "REGISTRY_REVISION_STALE"

    def __init__(self, expected_registry_revision: int, current_registry_revision: int) -> None:
        self.expected_registry_revision = expected_registry_revision
        self.current_registry_revision = current_registry_revision
        super().__init__(
            f"{self.code}: expected={expected_registry_revision}, current={current_registry_revision}"
        )


class PluginRegistryAuthority:
    """Pluginの宣言・permission・healthを短い同期的commitで公開するDomain Authority。"""

    def __init__(self) -> None:
        self._plugins: dict[str, RegisteredPluginView] = {}
        self._capabilities: dict[str, RegisteredCapabilityView] = {}
        self._tombstones: dict[str, int] = {}
        self._generations: dict[str, int] = {}
        self._observations: dict[str, PluginHealthObservation] = {}
        self._grants: PluginPermissionGrantSnapshot | None = None
        self._revision = 0
        self._lock = RLock()

    def snapshot(self, captured_at: datetime | None = None) -> PluginRegistrySnapshot:
        when = captured_at or datetime.now(timezone.utc)
        require_aware(when, "captured_at")
        with self._lock:
            capabilities = tuple(
                sorted(self._capabilities.values(), key=lambda item: item.declaration.capability_id)
            )
            descriptors = tuple(
                item
                for item in (project_capability(view) for view in capabilities)
                if item is not None
            )
            return PluginRegistrySnapshot(
                self._revision,
                tuple(sorted(self._plugins.values(), key=lambda item: item.manifest.plugin_id)),
                capabilities,
                descriptors,
                when,
            )

    def capability_descriptors(self) -> tuple[CapabilityDescriptor, ...]:
        return self.snapshot().foundation_capabilities

    def discover(
        self,
        manifest: PluginManifest,
        occurred_at: datetime,
        *,
        expected_registry_revision: int | None = None,
    ) -> RegisteredPluginView:
        return self._admit(
            manifest,
            PluginLifecycleState.DISCOVERED,
            occurred_at,
            expected_registry_revision=expected_registry_revision,
        )

    def validate(
        self,
        plugin_id: str,
        occurred_at: datetime,
        *,
        expected_registry_revision: int | None = None,
    ) -> RegisteredPluginView:
        return self._transition(
            plugin_id,
            PluginLifecycleState.DISCOVERED,
            PluginLifecycleState.VALIDATED,
            occurred_at,
            expected_registry_revision=expected_registry_revision,
        )

    def register(
        self,
        plugin_id: str,
        occurred_at: datetime,
        *,
        expected_registry_revision: int | None = None,
    ) -> RegisteredPluginView:
        return self._transition(
            plugin_id,
            PluginLifecycleState.VALIDATED,
            PluginLifecycleState.REGISTERED,
            occurred_at,
            expected_registry_revision=expected_registry_revision,
        )

    def register_manifest(
        self,
        manifest: PluginManifest,
        occurred_at: datetime,
        *,
        expected_registry_revision: int | None = None,
    ) -> RegisteredPluginView:
        return self._admit(
            manifest,
            PluginLifecycleState.REGISTERED,
            occurred_at,
            expected_registry_revision=expected_registry_revision,
        )

    def adopt_permission_grants(
        self,
        snapshot: PluginPermissionGrantSnapshot,
        *,
        expected_registry_revision: int | None = None,
    ) -> PluginRegistrySnapshot:
        if not isinstance(snapshot, PluginPermissionGrantSnapshot):
            raise ValueError("grant snapshot が不正です")
        with self._lock:
            self._require_expected_revision_locked(expected_registry_revision)
            previous = self._grants
            if previous is not None:
                if snapshot.grant_revision < previous.grant_revision:
                    raise ValueError("grant revision がstaleです")
                if snapshot.grant_revision == previous.grant_revision:
                    if snapshot != previous:
                        raise ValueError("同一grant revisionのpayloadが不一致です")
                    return self.snapshot(snapshot.captured_at)
            before = self._visible_state_locked()
            self._grants = snapshot
            self._rebuild_locked()
            self._advance_revision_if_visible_changed_locked(before)
            return self.snapshot(snapshot.captured_at)

    def apply_health_observation(
        self, observation: PluginHealthObservation
    ) -> PluginRegistrySnapshot:
        if not isinstance(observation, PluginHealthObservation):
            raise ValueError("health observation が不正です")
        with self._lock:
            plugin = self._plugins.get(observation.plugin_id)
            if plugin is None or plugin.lifecycle_state is PluginLifecycleState.UNREGISTERED:
                raise ValueError("health observationのPluginが未登録です")
            if observation.plugin_generation != plugin.plugin_generation:
                raise ValueError("health observationのgenerationがstaleです")
            known = {item.capability_id for item in plugin.manifest.capabilities}
            if any(item.capability_id not in known for item in observation.capability_health):
                raise ValueError("health observationに未知capabilityがあります")
            previous = self._observations.get(observation.plugin_id)
            if previous is not None:
                if observation.observation_revision < previous.observation_revision:
                    raise ValueError("health observation revisionがstaleです")
                if observation.observation_revision == previous.observation_revision:
                    if observation != previous:
                        raise ValueError("同一health observation revisionのpayloadが不一致です")
                    return self.snapshot(observation.observed_at)
                if utc_instant(observation.observed_at) < utc_instant(previous.observed_at):
                    raise ValueError("health observation時刻を巻き戻せません")
            if plugin.lifecycle_state in {
                PluginLifecycleState.STOPPING,
                PluginLifecycleState.STOPPED,
            }:
                return self.snapshot(observation.observed_at)
            before = self._visible_state_locked()
            self._observations[observation.plugin_id] = observation
            self._rebuild_locked()
            self._advance_revision_if_visible_changed_locked(before)
            return self.snapshot(observation.observed_at)

    def begin_stop(
        self,
        plugin_id: str,
        occurred_at: datetime,
        *,
        expected_registry_revision: int | None = None,
    ) -> RegisteredPluginView:
        return self._transition(
            plugin_id,
            (
                PluginLifecycleState.REGISTERED,
                PluginLifecycleState.AVAILABLE,
                PluginLifecycleState.DEGRADED,
                PluginLifecycleState.UNAVAILABLE,
            ),
            PluginLifecycleState.STOPPING,
            occurred_at,
            expected_registry_revision=expected_registry_revision,
        )

    def mark_stopped(
        self,
        plugin_id: str,
        occurred_at: datetime,
        *,
        expected_registry_revision: int | None = None,
    ) -> RegisteredPluginView:
        return self._transition(
            plugin_id,
            PluginLifecycleState.STOPPING,
            PluginLifecycleState.STOPPED,
            occurred_at,
            expected_registry_revision=expected_registry_revision,
        )

    def unregister(
        self,
        plugin_id: str,
        occurred_at: datetime,
        *,
        expected_registry_revision: int | None = None,
    ) -> None:
        require_aware(occurred_at, "occurred_at")
        with self._lock:
            self._require_expected_revision_locked(expected_registry_revision)
            plugin = self._plugins.get(plugin_id)
            if plugin is None or plugin.lifecycle_state is not PluginLifecycleState.STOPPED:
                raise ValueError("停止済みPluginだけunregisterできます")
            before = self._visible_state_locked()
            for declaration in plugin.manifest.capabilities:
                view = self._capabilities.pop(declaration.capability_id)
                self._tombstones[declaration.capability_id] = view.capability_revision
            self._plugins.pop(plugin_id)
            self._observations.pop(plugin_id, None)
            self._advance_revision_if_visible_changed_locked(before)

    def _admit(
        self,
        manifest: PluginManifest,
        state: PluginLifecycleState,
        occurred_at: datetime,
        *,
        expected_registry_revision: int | None,
    ) -> RegisteredPluginView:
        if not isinstance(manifest, PluginManifest):
            raise ValueError("manifest が不正です")
        require_aware(occurred_at, "occurred_at")
        with self._lock:
            self._require_expected_revision_locked(expected_registry_revision)
            if manifest.plugin_id in self._plugins:
                raise ValueError("Pluginはすでにactiveです")
            collisions = {item.capability_id for item in manifest.capabilities} & set(
                self._capabilities
            )
            if collisions:
                raise ValueError("capability_idが既存Pluginと衝突します")
            before = self._visible_state_locked()
            generation = self._generations.get(manifest.plugin_id, -1) + 1
            plugin = RegisteredPluginView(
                manifest, generation, state, PluginHealthState.UNKNOWN, ()
            )
            self._plugins[manifest.plugin_id] = plugin
            for declaration in manifest.capabilities:
                floor = self._tombstones.get(declaration.capability_id, -1)
                self._capabilities[declaration.capability_id] = self._view(
                    declaration, plugin, floor + 1
                )
            self._generations[manifest.plugin_id] = generation
            self._advance_revision_if_visible_changed_locked(before)
            return plugin

    def _transition(
        self,
        plugin_id: str,
        before: PluginLifecycleState | tuple[PluginLifecycleState, ...],
        after: PluginLifecycleState,
        occurred_at: datetime,
        *,
        expected_registry_revision: int | None,
    ) -> RegisteredPluginView:
        require_aware(occurred_at, "occurred_at")
        with self._lock:
            self._require_expected_revision_locked(expected_registry_revision)
            plugin = self._plugins.get(plugin_id)
            allowed = before if isinstance(before, tuple) else (before,)
            if plugin is None or plugin.lifecycle_state not in allowed:
                raise ValueError("Plugin lifecycle transitionが不正です")
            visible_before = self._visible_state_locked()
            plugin = replace(plugin, lifecycle_state=after)
            self._plugins[plugin_id] = plugin
            self._rebuild_locked()
            self._advance_revision_if_visible_changed_locked(visible_before)
            return self._plugins[plugin_id]

    def _rebuild_locked(self) -> None:
        updated: dict[str, RegisteredCapabilityView] = {}
        plugin_updates: dict[str, RegisteredPluginView] = {}
        for plugin_id, plugin in self._plugins.items():
            observation = self._observations.get(plugin_id)
            states = (
                {item.capability_id: item.health for item in observation.capability_health}
                if observation
                else {}
            )
            views = []
            missing_all: list[PluginPermissionRef] = []
            for declaration in plugin.manifest.capabilities:
                old = self._capabilities[declaration.capability_id]
                candidate = self._view(
                    declaration,
                    plugin,
                    old.capability_revision,
                    observation_health=states.get(declaration.capability_id),
                    plugin_health=observation.plugin_health
                    if observation
                    else PluginHealthState.UNKNOWN,
                )
                if self._projection_key(old) != self._projection_key(candidate):
                    candidate = replace(candidate, capability_revision=old.capability_revision + 1)
                updated[declaration.capability_id] = candidate
                views.append(candidate)
                missing_all.extend(candidate.missing_permissions)
            health = observation.plugin_health if observation else PluginHealthState.UNKNOWN
            lifecycle = plugin.lifecycle_state
            if lifecycle in {
                PluginLifecycleState.REGISTERED,
                PluginLifecycleState.AVAILABLE,
                PluginLifecycleState.DEGRADED,
                PluginLifecycleState.UNAVAILABLE,
            }:
                availability = {item.effective_availability for item in views}
                if CapabilityAvailability.AVAILABLE in availability:
                    lifecycle = PluginLifecycleState.AVAILABLE
                elif CapabilityAvailability.DEGRADED in availability:
                    lifecycle = PluginLifecycleState.DEGRADED
                else:
                    lifecycle = PluginLifecycleState.UNAVAILABLE
            plugin_updates[plugin_id] = replace(
                plugin,
                lifecycle_state=lifecycle,
                health_state=health,
                missing_permissions=tuple(dict.fromkeys(missing_all)),
            )
        self._capabilities = updated
        self._plugins = plugin_updates

    def _view(
        self,
        declaration: PluginCapabilityDeclaration,
        plugin: RegisteredPluginView,
        revision: int,
        *,
        observation_health: PluginHealthState | None = None,
        plugin_health: PluginHealthState = PluginHealthState.UNKNOWN,
    ) -> RegisteredCapabilityView:
        required = (*plugin.manifest.required_permissions, *declaration.required_permissions)
        grants = self._grants.grants if self._grants is not None else ()
        permitted = []
        missing: list[PluginPermissionRef] = []
        for operation in declaration.operations:
            operation_required = (*required, *operation.required_permissions)
            unavailable = [
                permission
                for permission in operation_required
                if not any(
                    grant.plugin_id == plugin.manifest.plugin_id and grant.permission == permission
                    for grant in grants
                )
            ]
            if unavailable:
                missing.extend(unavailable)
            else:
                permitted.append(operation)
        lifecycle = plugin.lifecycle_state
        health = observation_health or plugin_health
        if (
            lifecycle
            not in {
                PluginLifecycleState.REGISTERED,
                PluginLifecycleState.AVAILABLE,
                PluginLifecycleState.DEGRADED,
                PluginLifecycleState.UNAVAILABLE,
            }
            or not permitted
        ):
            availability = CapabilityAvailability.UNAVAILABLE
        elif health is PluginHealthState.UNAVAILABLE:
            availability = CapabilityAvailability.UNAVAILABLE
        elif health is PluginHealthState.DEGRADED:
            availability = CapabilityAvailability.DEGRADED
        elif health is PluginHealthState.UNKNOWN:
            availability = CapabilityAvailability.UNKNOWN
        else:
            availability = CapabilityAvailability.AVAILABLE
        all_required = tuple(
            dict.fromkeys(
                permission
                for operation in declaration.operations
                for permission in (*required, *operation.required_permissions)
            )
        )
        return RegisteredCapabilityView(
            declaration,
            plugin.manifest.plugin_id,
            plugin.manifest.plugin_version,
            plugin.manifest.contract_version,
            plugin.plugin_generation,
            revision,
            availability,
            tuple(permitted),
            all_required,
            tuple(dict.fromkeys(missing)),
        )

    def _require_expected_revision_locked(self, expected_registry_revision: int | None) -> None:
        require_revision(
            expected_registry_revision,
            "expected_registry_revision",
            optional=True,
        )
        if (
            expected_registry_revision is not None
            and expected_registry_revision != self._revision
        ):
            raise PluginRegistryRevisionStaleError(
                expected_registry_revision,
                self._revision,
            )

    def _visible_state_locked(
        self,
    ) -> tuple[
        dict[str, RegisteredPluginView],
        dict[str, RegisteredCapabilityView],
    ]:
        return dict(self._plugins), dict(self._capabilities)

    def _advance_revision_if_visible_changed_locked(
        self,
        before: tuple[
            dict[str, RegisteredPluginView],
            dict[str, RegisteredCapabilityView],
        ],
    ) -> None:
        plugins_before, capabilities_before = before
        if self._plugins != plugins_before or self._capabilities != capabilities_before:
            self._revision += 1

    @staticmethod
    def _projection_key(view: RegisteredCapabilityView) -> tuple[object, ...]:
        return (
            view.plugin_generation,
            view.effective_availability,
            view.permitted_operations,
            view.required_permissions,
            view.missing_permissions,
        )
