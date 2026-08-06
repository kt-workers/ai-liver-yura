from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AutonomousContinuationAction(str, Enum):
    CONTINUE = "continue"
    COMPLETE = "complete"


@dataclass(frozen=True, slots=True)
class AutonomousContinuationEvaluation:
    action: AutonomousContinuationAction
    reason: str
    continuation_strength: float
    turn_count: int
    waiting_for_user: bool = False
    hard_limit_reached: bool = False

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("reasonは空にできません。")
        if self.turn_count < 0:
            raise ValueError("turn_countは0以上にしてください。")
        object.__setattr__(
            self,
            "continuation_strength",
            max(-1.0, min(1.0, float(self.continuation_strength))),
        )

    @property
    def should_complete(self) -> bool:
        return self.action is AutonomousContinuationAction.COMPLETE

    def as_context(self) -> dict[str, object]:
        return {
            "action": self.action.value,
            "reason": self.reason,
            "continuation_strength": self.continuation_strength,
            "turn_count": self.turn_count,
            "waiting_for_user": self.waiting_for_user,
            "hard_limit_reached": self.hard_limit_reached,
        }
