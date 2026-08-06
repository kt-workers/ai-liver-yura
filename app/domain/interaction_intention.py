from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


def _clamp_01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


class InteractionIntentionType(str, Enum):
    """発話文・Activity実装より上流に置く有限の対人的意図。"""

    ANSWER = "answer"
    ACKNOWLEDGE = "acknowledge"
    LISTEN = "listen"
    ASK = "ask"
    SHARE = "share"
    INVITE = "invite"
    COMFORT = "comfort"
    SET_BOUNDARY = "set_boundary"
    PAUSE = "pause"
    ACT = "act"
    OBSERVE = "observe"


@dataclass(frozen=True, slots=True)
class InteractionIntention:
    intention: InteractionIntentionType
    confidence: float
    source: str
    reason: str
    primary_desire: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    activity_type: str | None = None
    operation: str | None = None
    requires_response: bool = True

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise ValueError("sourceは空にできません。")
        if not self.reason.strip():
            raise ValueError("reasonは空にできません。")
        object.__setattr__(self, "confidence", _clamp_01(self.confidence))
        for field_name in (
            "primary_desire",
            "target_type",
            "target_id",
            "activity_type",
            "operation",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_text(getattr(self, field_name)),
            )

    def as_context(self) -> dict[str, object]:
        return {
            "intention": self.intention.value,
            "confidence": self.confidence,
            "source": self.source,
            "reason": self.reason,
            "primary_desire": self.primary_desire,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "activity_type": self.activity_type,
            "operation": self.operation,
            "requires_response": self.requires_response,
            "observation_only": True,
        }


@dataclass(frozen=True, slots=True)
class InteractionIntentionComparison:
    expected: InteractionIntentionType
    directive_projection: InteractionIntentionType
    exact_match: bool
    compatible: bool
    comparison_stage: str
    reason: str

    def __post_init__(self) -> None:
        if not self.comparison_stage.strip():
            raise ValueError("comparison_stageは空にできません。")
        if not self.reason.strip():
            raise ValueError("reasonは空にできません。")

    def as_context(self) -> dict[str, object]:
        return {
            "expected": self.expected.value,
            "directive_projection": self.directive_projection.value,
            "exact_match": self.exact_match,
            "compatible": self.compatible,
            "comparison_stage": self.comparison_stage,
            "reason": self.reason,
            "observation_only": True,
        }
