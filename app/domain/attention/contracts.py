from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum, IntEnum

from app.domain.contracts.common import (
    require_aware,
    require_identifier,
    require_revision,
    timestamp_to_json,
    utc_instant,
)


class AttentionSourceKind(str, Enum):
    USER_INTERACTION = "user_interaction"
    GOAL = "goal"
    COMMITMENT = "commitment"
    ACTIVITY = "activity"
    APPRAISAL = "appraisal"
    STREAMING = "streaming"
    GAME = "game"
    REFLECTION = "reflection"
    AUTONOMOUS = "autonomous"


class AttentionPriority(IntEnum):
    BACKGROUND = 0
    NORMAL = 1
    FOREGROUND = 2
    DIRECT_USER = 3


class AttentionTransitionOperation(str, Enum):
    ACQUIRE_FOREGROUND = "acquire_foreground"
    RELEASE_FOREGROUND = "release_foreground"
    ADD_MONITOR = "add_monitor"
    REMOVE_MONITOR = "remove_monitor"
    ASSIGN_TURN = "assign_turn"
    RELEASE_TURN = "release_turn"
    SET_RESPONSE_OBLIGATION = "set_response_obligation"
    CLEAR_RESPONSE_OBLIGATION = "clear_response_obligation"


def _ids(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise ValueError(f"{name} は配列でなければなりません")
    result = tuple(value)
    if any(not isinstance(item, str) or not item.strip() for item in result) or len(result) != len(
        set(result)
    ):
        raise ValueError(f"{name} は一意な識別子の配列でなければなりません")
    return result


@dataclass(frozen=True, slots=True)
class AttentionSource:
    source_ref: str
    kind: AttentionSourceKind
    priority: AttentionPriority
    occurred_at: datetime
    coalesced_count: int = 1

    def __post_init__(self) -> None:
        require_identifier(self.source_ref, "source_ref")
        if not isinstance(self.kind, AttentionSourceKind) or not isinstance(
            self.priority, AttentionPriority
        ):
            raise ValueError("source kind と priority は型付き列挙値でなければなりません")
        if (
            self.kind is AttentionSourceKind.USER_INTERACTION
            and self.priority is not AttentionPriority.DIRECT_USER
        ):
            raise ValueError("user interactionはdirect user priorityでなければなりません")
        require_aware(self.occurred_at, "occurred_at")
        if type(self.coalesced_count) is not int or self.coalesced_count < 1:
            raise ValueError("coalesced_count は正の整数でなければなりません")

    def to_dict(self) -> dict[str, object]:
        return {
            "source_ref": self.source_ref,
            "kind": self.kind.value,
            "priority": self.priority.name.lower(),
            "occurred_at": timestamp_to_json(self.occurred_at),
            "coalesced_count": self.coalesced_count,
        }


@dataclass(frozen=True, slots=True)
class AttentionFocusState:
    revision: int
    source_context_revision: int
    foreground_focus_ref: str | None
    secondary_monitor_refs: tuple[str, ...]
    current_turn_owner: str | None
    response_obligation: str | None
    attention_budget: int
    sources: tuple[AttentionSource, ...]
    updated_at: datetime

    def __post_init__(self) -> None:
        require_revision(self.revision, "revision")
        require_revision(self.source_context_revision, "source_context_revision")
        for name in ("foreground_focus_ref", "current_turn_owner", "response_obligation"):
            value = getattr(self, name)
            if value is not None:
                require_identifier(value, name)
        object.__setattr__(
            self,
            "secondary_monitor_refs",
            _ids(self.secondary_monitor_refs, "secondary_monitor_refs"),
        )
        if self.foreground_focus_ref in self.secondary_monitor_refs:
            raise ValueError("foreground はsecondary monitorと重複できません")
        if type(self.attention_budget) is not int or self.attention_budget < 1:
            raise ValueError("attention_budget は正の整数でなければなりません")
        if not isinstance(self.sources, (tuple, list)) or any(
            not isinstance(item, AttentionSource) for item in self.sources
        ):
            raise ValueError("sources は AttentionSource の配列でなければなりません")
        sources = tuple(self.sources)
        if len(sources) > self.attention_budget or len(
            {item.source_ref for item in sources}
        ) != len(sources):
            raise ValueError("sources はbudget内の一意なsourceでなければなりません")
        require_aware(self.updated_at, "updated_at")
        if any(utc_instant(item.occurred_at) > utc_instant(self.updated_at) for item in sources):
            raise ValueError("sourceはsnapshotより新しくできません")
        object.__setattr__(self, "sources", sources)

    def to_dict(self) -> dict[str, object]:
        return {
            "revision": self.revision,
            "source_context_revision": self.source_context_revision,
            "foreground_focus_ref": self.foreground_focus_ref,
            "secondary_monitor_refs": list(self.secondary_monitor_refs),
            "current_turn_owner": self.current_turn_owner,
            "response_obligation": self.response_obligation,
            "attention_budget": self.attention_budget,
            "sources": [item.to_dict() for item in self.sources],
            "updated_at": timestamp_to_json(self.updated_at),
        }


AttentionFocusView = AttentionFocusState


@dataclass(frozen=True, slots=True)
class AttentionTransition:
    transition_id: str
    operation: AttentionTransitionOperation
    expected_attention_revision: int
    occurred_at: datetime
    target_ref: str | None = None
    value: str | None = None

    def __post_init__(self) -> None:
        require_identifier(self.transition_id, "transition_id")
        if not isinstance(self.operation, AttentionTransitionOperation):
            raise ValueError("operation は AttentionTransitionOperation でなければなりません")
        require_revision(self.expected_attention_revision, "expected_attention_revision")
        require_aware(self.occurred_at, "occurred_at")
        for name in ("target_ref", "value"):
            item = getattr(self, name)
            if item is not None:
                require_identifier(item, name)
        needs_target = {
            AttentionTransitionOperation.ACQUIRE_FOREGROUND,
            AttentionTransitionOperation.ADD_MONITOR,
            AttentionTransitionOperation.REMOVE_MONITOR,
        }
        needs_value = {
            AttentionTransitionOperation.ASSIGN_TURN,
            AttentionTransitionOperation.SET_RESPONSE_OBLIGATION,
        }
        if (self.operation in needs_target) != (self.target_ref is not None) or (
            self.operation in needs_value
        ) != (self.value is not None):
            raise ValueError("transitionのoperationとpayloadが一致しません")
        if self.operation not in needs_target and self.target_ref is not None:
            raise ValueError("このoperationにtarget_refは指定できません")
        if self.operation not in needs_value and self.value is not None:
            raise ValueError("このoperationにvalueは指定できません")

    def to_dict(self) -> dict[str, object]:
        return {
            "transition_id": self.transition_id,
            "operation": self.operation.value,
            "expected_attention_revision": self.expected_attention_revision,
            "occurred_at": timestamp_to_json(self.occurred_at),
            "target_ref": self.target_ref,
            "value": self.value,
        }


@dataclass(frozen=True, slots=True)
class ExecutiveTriggerEligibility:
    trigger_id: str
    source_ref: str
    reason_kind: AttentionSourceKind
    priority: AttentionPriority
    source_context_revision: int
    goal_revision: int
    attention_revision: int
    created_at: datetime

    def __post_init__(self) -> None:
        require_identifier(self.trigger_id, "trigger_id")
        require_identifier(self.source_ref, "source_ref")
        if not isinstance(self.reason_kind, AttentionSourceKind) or not isinstance(
            self.priority, AttentionPriority
        ):
            raise ValueError("reason_kind とpriorityは型付き列挙値でなければなりません")
        for name in ("source_context_revision", "goal_revision", "attention_revision"):
            require_revision(getattr(self, name), name)
        require_aware(self.created_at, "created_at")

    def to_dict(self) -> dict[str, object]:
        return {
            "trigger_id": self.trigger_id,
            "source_ref": self.source_ref,
            "reason_kind": self.reason_kind.value,
            "priority": self.priority.name.lower(),
            "source_context_revision": self.source_context_revision,
            "goal_revision": self.goal_revision,
            "attention_revision": self.attention_revision,
            "created_at": timestamp_to_json(self.created_at),
        }
