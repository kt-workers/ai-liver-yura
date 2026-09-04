from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite

from app.domain.contracts.common import (
    JsonValue,
    freeze_json,
    require_aware,
    require_identifier,
    require_revision,
    thaw_json,
)


class GuiAdminReadModelKind(str, Enum):
    SYSTEM_HEALTH = "system_health"
    RUNTIME_LIFECYCLE = "runtime_lifecycle"
    INTERNAL_STATE_SUMMARY = "internal_state_summary"
    GOAL_COMMITMENT_SUMMARY = "goal_commitment_summary"
    ATTENTION_FOCUS_SUMMARY = "attention_focus_summary"
    ACTIVITY_SUMMARY = "activity_summary"
    SPEECH_RUNTIME_SUMMARY = "speech_runtime_summary"
    BODY_SUMMARY = "body_summary"
    PLUGIN_CAPABILITY_SUMMARY = "plugin_capability_summary"
    SUBSYSTEM_HEALTH_SUMMARY = "subsystem_health_summary"
    PROVIDER_DIAGNOSTIC_SUMMARY = "provider_diagnostic_summary"
    CONFIGURATION_SUMMARY = "configuration_summary"


class GuiAdminAvailability(str, Enum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class AdminCommandStatus(str, Enum):
    APPLIED = "applied"
    REJECTED = "rejected"
    STALE_ADMIN_VIEW = "stale_admin_view"
    DUPLICATE = "duplicate"
    TIMED_OUT = "timed_out"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


def _positive_int(value: object, name: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{name} は1以上の整数でなければなりません")
    assert isinstance(value, int)
    if value < 1:
        raise ValueError(f"{name} は1以上の整数でなければなりません")
    return value


def _positive_finite(value: object, name: str) -> float:
    if type(value) not in (int, float) or isinstance(value, bool):
        raise ValueError(f"{name} は正の有限数でなければなりません")
    assert isinstance(value, (int, float))
    normalized = float(value)
    if not isfinite(normalized) or normalized <= 0:
        raise ValueError(f"{name} は正の有限数でなければなりません")
    return normalized


def _reason_codes(values: tuple[str, ...]) -> tuple[str, ...]:
    if (
        not isinstance(values, tuple)
        or any(not isinstance(value, str) or not value.strip() for value in values)
        or len(values) != len(set(values))
    ):
        raise ValueError("degraded_reasons が不正です")
    return values


def json_payload_size_bytes(value: JsonValue) -> int:
    return len(
        json.dumps(
            thaw_json(value),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )


@dataclass(frozen=True, slots=True)
class GuiAdminOperationalPolicy:
    policy_id: str = "v2.gui-admin.default"
    policy_revision: int = 1
    max_read_model_payload_bytes: int = 262144
    max_command_payload_bytes: int = 65536
    per_client_update_capacity: int = 32
    max_history_page_items: int = 200
    max_active_subscriptions_per_client: int = 64
    command_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        require_identifier(self.policy_id, "policy_id")
        require_revision(self.policy_revision, "policy_revision")
        for name in (
            "max_read_model_payload_bytes",
            "max_command_payload_bytes",
            "per_client_update_capacity",
            "max_history_page_items",
            "max_active_subscriptions_per_client",
        ):
            object.__setattr__(self, name, _positive_int(getattr(self, name), name))
        object.__setattr__(
            self,
            "command_timeout_seconds",
            _positive_finite(self.command_timeout_seconds, "command_timeout_seconds"),
        )


@dataclass(frozen=True, slots=True)
class AdminReadModelEnvelope:
    model_kind: GuiAdminReadModelKind
    schema_version: int
    source_owner: str
    source_revision: int
    generated_at: datetime
    payload: JsonValue
    availability: GuiAdminAvailability = GuiAdminAvailability.AVAILABLE
    degraded_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.model_kind, GuiAdminReadModelKind):
            raise ValueError("model_kind が不正です")
        if type(self.schema_version) is not int or self.schema_version < 1:
            raise ValueError("schema_version は1以上の整数でなければなりません")
        require_identifier(self.source_owner, "source_owner")
        require_revision(self.source_revision, "source_revision")
        require_aware(self.generated_at, "generated_at")
        object.__setattr__(self, "payload", freeze_json(self.payload))
        if not isinstance(self.availability, GuiAdminAvailability):
            raise ValueError("availability が不正です")
        reasons = _reason_codes(self.degraded_reasons)
        if self.availability is GuiAdminAvailability.AVAILABLE and reasons:
            raise ValueError("AVAILABLEのRead Modelにdegraded_reasonsは指定できません")
        if self.availability is not GuiAdminAvailability.AVAILABLE and not reasons:
            raise ValueError("degraded/unavailableにはdegraded_reasonsが必要です")
        object.__setattr__(self, "degraded_reasons", reasons)

    @property
    def identity(self) -> tuple[GuiAdminReadModelKind, str]:
        return self.model_kind, self.source_owner

    @property
    def payload_size_bytes(self) -> int:
        return json_payload_size_bytes(self.payload)


@dataclass(frozen=True, slots=True)
class AdminCommandRequest:
    command_id: str
    command_kind: str
    target_owner: str
    target_ref: str | None
    expected_revision: int | None
    payload: JsonValue
    requested_at: datetime
    actor_context: JsonValue

    def __post_init__(self) -> None:
        for name in ("command_id", "command_kind", "target_owner"):
            require_identifier(getattr(self, name), name)
        if self.target_ref is not None:
            require_identifier(self.target_ref, "target_ref")
        require_revision(self.expected_revision, "expected_revision", optional=True)
        require_aware(self.requested_at, "requested_at")
        object.__setattr__(self, "payload", freeze_json(self.payload))
        object.__setattr__(self, "actor_context", freeze_json(self.actor_context))

    @property
    def payload_size_bytes(self) -> int:
        return json_payload_size_bytes(self.payload)


@dataclass(frozen=True, slots=True)
class AdminCommandResult:
    command_id: str
    status: AdminCommandStatus
    owner_revision_before: int | None = None
    owner_revision_after: int | None = None
    applied_at: datetime | None = None
    failure_code: str | None = None
    sanitized_message: str | None = None

    def __post_init__(self) -> None:
        require_identifier(self.command_id, "command_id")
        if not isinstance(self.status, AdminCommandStatus):
            raise ValueError("status が不正です")
        require_revision(self.owner_revision_before, "owner_revision_before", optional=True)
        require_revision(self.owner_revision_after, "owner_revision_after", optional=True)
        if (
            self.owner_revision_before is not None
            and self.owner_revision_after is not None
            and self.owner_revision_after < self.owner_revision_before
        ):
            raise ValueError("owner revisionは単調増加でなければなりません")
        if self.status is AdminCommandStatus.APPLIED:
            if self.applied_at is None:
                raise ValueError("APPLIEDにはapplied_atが必要です")
            if self.failure_code is not None:
                raise ValueError("APPLIEDにfailure_codeは指定できません")
        else:
            if self.applied_at is not None:
                raise ValueError("未確認結果にapplied_atは指定できません")
            if self.failure_code is None:
                raise ValueError("APPLIED以外にはfailure_codeが必要です")
        if self.applied_at is not None:
            require_aware(self.applied_at, "applied_at")
        if self.failure_code is not None:
            require_identifier(self.failure_code, "failure_code")
        if self.sanitized_message is not None and (
            not isinstance(self.sanitized_message, str) or not self.sanitized_message.strip()
        ):
            raise ValueError("sanitized_message が不正です")


__all__ = [
    "AdminCommandRequest",
    "AdminCommandResult",
    "AdminCommandStatus",
    "AdminReadModelEnvelope",
    "GuiAdminAvailability",
    "GuiAdminOperationalPolicy",
    "GuiAdminReadModelKind",
    "json_payload_size_bytes",
]
