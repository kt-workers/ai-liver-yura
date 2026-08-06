from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.domain.interaction_intention import InteractionIntention


class AutonomousInteractionAction(str, Enum):
    """自律的な対人Activityを今始めるかの有限判断。"""

    START = "start"
    WAIT = "wait"
    OBSERVE = "observe"


@dataclass(frozen=True, slots=True)
class AutonomousInteractionDecision:
    action: AutonomousInteractionAction
    interaction_intention: InteractionIntention
    confidence: float
    reason: str
    legacy_drive_ready: bool
    conversation_resume_reason: str | None = None
    topic_continuation: str | None = None

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("reasonは空にできません。")
        object.__setattr__(
            self,
            "confidence",
            max(0.0, min(1.0, float(self.confidence))),
        )
        for field_name in ("conversation_resume_reason", "topic_continuation"):
            value = getattr(self, field_name)
            if value is not None:
                normalized = value.strip()
                object.__setattr__(self, field_name, normalized or None)

    @property
    def should_start(self) -> bool:
        return self.action is AutonomousInteractionAction.START

    def as_context(self) -> dict[str, object]:
        return {
            "action": self.action.value,
            "interaction_intention": self.interaction_intention.as_context(),
            "confidence": self.confidence,
            "reason": self.reason,
            "legacy_drive_ready": self.legacy_drive_ready,
            "conversation_resume_reason": self.conversation_resume_reason,
            "topic_continuation": self.topic_continuation,
        }


@dataclass(frozen=True, slots=True)
class AutonomousInteractionComparison:
    legacy_drive_ready: bool
    causal_should_start: bool
    matched: bool
    conservative_start_allowed: bool
    expansion_blocked: bool
    causal_vetoed_legacy_start: bool

    @classmethod
    def compare(
        cls,
        *,
        legacy_drive_ready: bool,
        causal_should_start: bool,
    ) -> AutonomousInteractionComparison:
        return cls(
            legacy_drive_ready=legacy_drive_ready,
            causal_should_start=causal_should_start,
            matched=legacy_drive_ready == causal_should_start,
            conservative_start_allowed=(
                legacy_drive_ready and causal_should_start
            ),
            expansion_blocked=(
                causal_should_start and not legacy_drive_ready
            ),
            causal_vetoed_legacy_start=(
                legacy_drive_ready and not causal_should_start
            ),
        )

    def as_context(self) -> dict[str, bool]:
        return {
            "legacy_drive_ready": self.legacy_drive_ready,
            "causal_should_start": self.causal_should_start,
            "matched": self.matched,
            "conservative_start_allowed": self.conservative_start_allowed,
            "expansion_blocked": self.expansion_blocked,
            "causal_vetoed_legacy_start": self.causal_vetoed_legacy_start,
        }
