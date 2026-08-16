from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite
from typing import TypeVar, cast

from app.domain.contracts import CapabilityAvailability, CapabilityDescriptor
from app.domain.contracts.common import (
    require_aware,
    require_identifier,
    require_revision,
)

SUPPORTED_PLUGIN_CONTRACT_VERSIONS = frozenset({1})


class PluginSideEffectClass(str, Enum):
    NONE = "none"
    OBSERVABLE_EXTERNAL = "observable_external"
    MUTATING_EXTERNAL = "mutating_external"


class PluginCancellationSupport(str, Enum):
    NONE = "none"
    SOFT = "soft"
    HARD = "hard"


class PluginLifecycleState(str, Enum):
    DISCOVERED = "discovered"
    VALIDATED = "validated"
    REGISTERED = "registered"
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    STOPPING = "stopping"
    STOPPED = "stopped"
    UNREGISTERED = "unregistered"


class PluginHealthState(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


T = TypeVar("T")


def _owned(values: object, item_type: type[T], name: str) -> tuple[T, ...]:
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{name} は配列でなければなりません")
    result = tuple(values)
    if any(not isinstance(item, item_type) for item in result):
        raise ValueError(f"{name} に不正な要素があります")
    return cast(tuple[T, ...], result)


def _unique(values: tuple[T, ...], key: str, name: str) -> tuple[T, ...]:
    identifiers = [getattr(item, key) for item in values]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError(f"{name} は重複できません")
    return values


@dataclass(frozen=True, slots=True)
class PluginPermissionRef:
    permission_id: str
    scope_ref: str | None = None

    def __post_init__(self) -> None:
        require_identifier(self.permission_id, "permission_id")
        if self.scope_ref is not None:
            require_identifier(self.scope_ref, "scope_ref")


@dataclass(frozen=True, slots=True)
class PluginPermissionGrant:
    plugin_id: str
    permission: PluginPermissionRef

    def __post_init__(self) -> None:
        require_identifier(self.plugin_id, "plugin_id")
        if not isinstance(self.permission, PluginPermissionRef):
            raise ValueError("permission は PluginPermissionRef でなければなりません")


@dataclass(frozen=True, slots=True)
class PluginPermissionGrantSnapshot:
    grant_revision: int
    grants: tuple[PluginPermissionGrant, ...]
    captured_at: datetime

    def __post_init__(self) -> None:
        require_revision(self.grant_revision, "grant_revision")
        grants = _owned(self.grants, PluginPermissionGrant, "grants")
        if len(
            {(g.plugin_id, g.permission.permission_id, g.permission.scope_ref) for g in grants}
        ) != len(grants):
            raise ValueError("grants は principal と permission の組を重複できません")
        object.__setattr__(self, "grants", grants)
        require_aware(self.captured_at, "captured_at")


@dataclass(frozen=True, slots=True)
class PluginTimeoutSupport:
    supports_deadline: bool
    supports_provider_timeout: bool

    def __post_init__(self) -> None:
        if (
            type(self.supports_deadline) is not bool
            or type(self.supports_provider_timeout) is not bool
        ):
            raise ValueError("timeout support は bool でなければなりません")


@dataclass(frozen=True, slots=True)
class PluginOperationDeclaration:
    operation_id: str
    input_schema_ref: str
    output_schema_ref: str
    side_effect_class: PluginSideEffectClass
    required_permissions: tuple[PluginPermissionRef, ...]
    cancellation_support: PluginCancellationSupport
    timeout_support: PluginTimeoutSupport

    def __post_init__(self) -> None:
        for name in ("operation_id", "input_schema_ref", "output_schema_ref"):
            require_identifier(getattr(self, name), name)
        if not isinstance(self.side_effect_class, PluginSideEffectClass):
            raise ValueError("side_effect_class が不正です")
        permissions = _unique(
            _owned(self.required_permissions, PluginPermissionRef, "required_permissions"),
            "permission_id",
            "required_permissions",
        )
        if len({(p.permission_id, p.scope_ref) for p in permissions}) != len(permissions):
            raise ValueError("required_permissions は重複できません")
        object.__setattr__(self, "required_permissions", permissions)
        if not isinstance(self.cancellation_support, PluginCancellationSupport):
            raise ValueError("cancellation_support が不正です")
        if not isinstance(self.timeout_support, PluginTimeoutSupport):
            raise ValueError("timeout_support が不正です")


@dataclass(frozen=True, slots=True)
class PluginCapabilityDeclaration:
    capability_id: str
    capability_type: str
    operations: tuple[PluginOperationDeclaration, ...]
    required_permissions: tuple[PluginPermissionRef, ...] = ()
    health_required: bool = True

    def __post_init__(self) -> None:
        require_identifier(self.capability_id, "capability_id")
        require_identifier(self.capability_type, "capability_type")
        operations = _unique(
            _owned(self.operations, PluginOperationDeclaration, "operations"),
            "operation_id",
            "operations",
        )
        if not operations:
            raise ValueError("operations は空にできません")
        object.__setattr__(self, "operations", operations)
        permissions = _owned(self.required_permissions, PluginPermissionRef, "required_permissions")
        if len({(p.permission_id, p.scope_ref) for p in permissions}) != len(permissions):
            raise ValueError("required_permissions は重複できません")
        object.__setattr__(self, "required_permissions", permissions)
        if type(self.health_required) is not bool:
            raise ValueError("health_required は bool でなければなりません")


@dataclass(frozen=True, slots=True)
class PluginDependencyRef:
    plugin_id: str
    contract_version: int | None = None

    def __post_init__(self) -> None:
        require_identifier(self.plugin_id, "plugin_id")
        require_revision(self.contract_version, "contract_version", optional=True)


@dataclass(frozen=True, slots=True)
class PluginResourceRequirement:
    resource_type: str
    amount: float
    unit: str

    def __post_init__(self) -> None:
        require_identifier(self.resource_type, "resource_type")
        require_identifier(self.unit, "unit")
        if (
            type(self.amount) not in (int, float)
            or isinstance(self.amount, bool)
            or not isfinite(float(self.amount))
            or self.amount < 0
        ):
            raise ValueError("amount は有限の非負数でなければなりません")
        object.__setattr__(self, "amount", float(self.amount))


@dataclass(frozen=True, slots=True)
class PluginLifecycleHook:
    hook_id: str
    event: str

    def __post_init__(self) -> None:
        require_identifier(self.hook_id, "hook_id")
        require_identifier(self.event, "event")


@dataclass(frozen=True, slots=True)
class PluginManifest:
    plugin_id: str
    plugin_version: str
    contract_version: int
    display_name: str
    capabilities: tuple[PluginCapabilityDeclaration, ...]
    required_permissions: tuple[PluginPermissionRef, ...] = ()
    optional_dependencies: tuple[PluginDependencyRef, ...] = ()
    resource_requirements: tuple[PluginResourceRequirement, ...] = ()
    lifecycle_hooks: tuple[PluginLifecycleHook, ...] = ()

    def __post_init__(self) -> None:
        for name in ("plugin_id", "plugin_version", "display_name"):
            require_identifier(getattr(self, name), name)
        require_revision(self.contract_version, "contract_version")
        if self.contract_version not in SUPPORTED_PLUGIN_CONTRACT_VERSIONS:
            raise ValueError("未対応の contract_version です")
        capabilities = _unique(
            _owned(self.capabilities, PluginCapabilityDeclaration, "capabilities"),
            "capability_id",
            "capabilities",
        )
        if not capabilities:
            raise ValueError("capabilities は空にできません")
        object.__setattr__(self, "capabilities", capabilities)
        for name, kind in (
            ("required_permissions", PluginPermissionRef),
            ("optional_dependencies", PluginDependencyRef),
            ("resource_requirements", PluginResourceRequirement),
            ("lifecycle_hooks", PluginLifecycleHook),
        ):
            values = _owned(getattr(self, name), kind, name)
            object.__setattr__(self, name, values)
        if any(item.plugin_id == self.plugin_id for item in self.optional_dependencies):
            raise ValueError("optional dependency は自分自身を参照できません")
        if len({(p.permission_id, p.scope_ref) for p in self.required_permissions}) != len(
            self.required_permissions
        ):
            raise ValueError("required_permissions は重複できません")
        if len({d.plugin_id for d in self.optional_dependencies}) != len(
            self.optional_dependencies
        ):
            raise ValueError("optional_dependencies は重複できません")
        if len({h.hook_id for h in self.lifecycle_hooks}) != len(self.lifecycle_hooks):
            raise ValueError("lifecycle_hooks は重複できません")


@dataclass(frozen=True, slots=True)
class PluginCapabilityHealth:
    capability_id: str
    health: PluginHealthState

    def __post_init__(self) -> None:
        require_identifier(self.capability_id, "capability_id")
        if not isinstance(self.health, PluginHealthState):
            raise ValueError("health が不正です")


@dataclass(frozen=True, slots=True)
class PluginHealthObservation:
    plugin_id: str
    plugin_generation: int
    observation_revision: int
    plugin_health: PluginHealthState
    capability_health: tuple[PluginCapabilityHealth, ...]
    observed_at: datetime

    def __post_init__(self) -> None:
        require_identifier(self.plugin_id, "plugin_id")
        require_revision(self.plugin_generation, "plugin_generation")
        require_revision(self.observation_revision, "observation_revision")
        if not isinstance(self.plugin_health, PluginHealthState):
            raise ValueError("plugin_health が不正です")
        capability_health = _unique(
            _owned(self.capability_health, PluginCapabilityHealth, "capability_health"),
            "capability_id",
            "capability_health",
        )
        object.__setattr__(self, "capability_health", capability_health)
        require_aware(self.observed_at, "observed_at")


@dataclass(frozen=True, slots=True)
class RegisteredPluginView:
    manifest: PluginManifest
    plugin_generation: int
    lifecycle_state: PluginLifecycleState
    health_state: PluginHealthState
    missing_permissions: tuple[PluginPermissionRef, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.manifest, PluginManifest)
            or not isinstance(self.lifecycle_state, PluginLifecycleState)
            or not isinstance(self.health_state, PluginHealthState)
        ):
            raise ValueError("Plugin view が不正です")
        require_revision(self.plugin_generation, "plugin_generation")
        object.__setattr__(
            self,
            "missing_permissions",
            _owned(self.missing_permissions, PluginPermissionRef, "missing_permissions"),
        )


@dataclass(frozen=True, slots=True)
class RegisteredCapabilityView:
    declaration: PluginCapabilityDeclaration
    plugin_id: str
    plugin_version: str
    contract_version: int
    plugin_generation: int
    capability_revision: int
    effective_availability: CapabilityAvailability
    permitted_operations: tuple[PluginOperationDeclaration, ...]
    required_permissions: tuple[PluginPermissionRef, ...]
    missing_permissions: tuple[PluginPermissionRef, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.declaration, PluginCapabilityDeclaration) or not isinstance(
            self.effective_availability, CapabilityAvailability
        ):
            raise ValueError("Capability view が不正です")
        require_identifier(self.plugin_id, "plugin_id")
        require_identifier(self.plugin_version, "plugin_version")
        require_revision(self.contract_version, "contract_version")
        require_revision(self.plugin_generation, "plugin_generation")
        require_revision(self.capability_revision, "capability_revision")
        object.__setattr__(
            self,
            "permitted_operations",
            _owned(self.permitted_operations, PluginOperationDeclaration, "permitted_operations"),
        )
        object.__setattr__(
            self,
            "required_permissions",
            _owned(self.required_permissions, PluginPermissionRef, "required_permissions"),
        )
        object.__setattr__(
            self,
            "missing_permissions",
            _owned(self.missing_permissions, PluginPermissionRef, "missing_permissions"),
        )


@dataclass(frozen=True, slots=True)
class PluginRegistrySnapshot:
    registry_revision: int
    plugins: tuple[RegisteredPluginView, ...]
    capabilities: tuple[RegisteredCapabilityView, ...]
    foundation_capabilities: tuple[CapabilityDescriptor, ...]
    captured_at: datetime

    def __post_init__(self) -> None:
        require_revision(self.registry_revision, "registry_revision")
        object.__setattr__(self, "plugins", _owned(self.plugins, RegisteredPluginView, "plugins"))
        object.__setattr__(
            self,
            "capabilities",
            _owned(self.capabilities, RegisteredCapabilityView, "capabilities"),
        )
        object.__setattr__(
            self,
            "foundation_capabilities",
            _owned(self.foundation_capabilities, CapabilityDescriptor, "foundation_capabilities"),
        )
        require_aware(self.captured_at, "captured_at")
