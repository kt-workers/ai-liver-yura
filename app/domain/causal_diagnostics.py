from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping


class RouteLifecycle(str, Enum):
    """判断経路が現在担う役割。"""

    ACTIVE = "active"
    COMPATIBILITY = "compatibility"
    SHADOW = "shadow"
    DEPRECATED = "deprecated"


class CausalDecisionStage(str, Enum):
    INTERACTION_INTENTION = "interaction_intention"
    AUTONOMOUS_START = "autonomous_start"
    CHARACTER_CLAIM = "character_claim"
    AUTONOMOUS_CONTINUATION = "autonomous_continuation"
    AUTONOMOUS_COMPLETION = "autonomous_completion"


class CausalDecisionOutcome(str, Enum):
    MATCHED = "matched"
    CONSERVATIVE_ALLOWED = "conservative_allowed"
    EXPANSION_BLOCKED = "expansion_blocked"
    CAUSAL_VETO = "causal_veto"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CONTINUE = "continue"
    COMPLETE = "complete"
    OBSERVED = "observed"


@dataclass(frozen=True, slots=True)
class CausalRouteDescriptor:
    name: str
    lifecycle: RouteLifecycle
    removable: bool
    reason: str
    replacement: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("name", "reason"):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name}は空にできません。")
            object.__setattr__(self, field_name, value)
        if self.replacement is not None:
            replacement = self.replacement.strip()
            object.__setattr__(self, "replacement", replacement or None)

    def as_context(self) -> dict[str, object]:
        return {
            "name": self.name,
            "lifecycle": self.lifecycle.value,
            "removable": self.removable,
            "reason": self.reason,
            "replacement": self.replacement,
        }


ScalarDiagnostic = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class CausalDecisionSnapshot:
    stage: CausalDecisionStage
    causal_route: CausalRouteDescriptor
    outcome: CausalDecisionOutcome
    reason: str
    legacy_route: CausalRouteDescriptor | None = None
    intention: str | None = None
    action: str | None = None
    accepted: bool | None = None
    metrics: Mapping[str, ScalarDiagnostic] = field(default_factory=dict)

    def __post_init__(self) -> None:
        reason = self.reason.strip()
        if not reason:
            raise ValueError("reasonは空にできません。")
        object.__setattr__(self, "reason", reason)
        for field_name in ("intention", "action"):
            value = getattr(self, field_name)
            if value is not None:
                normalized = value.strip()
                object.__setattr__(self, field_name, normalized or None)
        normalized_metrics: dict[str, ScalarDiagnostic] = {}
        for key, value in self.metrics.items():
            normalized_key = str(key).strip()
            if not normalized_key:
                raise ValueError("metricsのキーは空にできません。")
            if not isinstance(value, (str, int, float, bool, type(None))):
                raise TypeError("metricsには有限なscalar値だけを指定してください。")
            normalized_metrics[normalized_key] = value
        object.__setattr__(self, "metrics", normalized_metrics)

    def as_context(self) -> dict[str, object]:
        return {
            "stage": self.stage.value,
            "causal_route": self.causal_route.as_context(),
            "legacy_route": (
                self.legacy_route.as_context()
                if self.legacy_route is not None
                else None
            ),
            "outcome": self.outcome.value,
            "reason": self.reason,
            "intention": self.intention,
            "action": self.action,
            "accepted": self.accepted,
            "metrics": dict(self.metrics),
        }
