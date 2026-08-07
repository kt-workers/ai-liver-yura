from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum


class AwakeningLifecyclePhase(str, Enum):
    INITIALIZING = "initializing"
    WAKING = "waking"
    ORIENTING = "orienting"
    READY = "ready"


def _unit(name: str, value: float) -> float:
    normalized = float(value)
    if not math.isfinite(normalized) or not 0.0 <= normalized <= 1.0:
        raise ValueError(f"{name} must be between 0.0 and 1.0")
    return normalized


def _aware(name: str, value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class AwakeningAppraisal:
    """起動Contextを、表現やモーションではない連続的な覚醒意味へ評価した結果。"""

    restoration: float
    sleepiness: float
    activation_urge: float
    exploration_urge: float
    social_urge: float
    security_need: float
    orientation_need: float
    residual_affect_weight: float
    readiness: float
    reason: str

    def __post_init__(self) -> None:
        for name in (
            "restoration",
            "sleepiness",
            "activation_urge",
            "exploration_urge",
            "social_urge",
            "security_need",
            "orientation_need",
            "residual_affect_weight",
            "readiness",
        ):
            object.__setattr__(self, name, _unit(name, getattr(self, name)))
        object.__setattr__(self, "reason", self.reason.strip()[:240])

    def as_context(self) -> dict[str, object]:
        return {
            "restoration": self.restoration,
            "sleepiness": self.sleepiness,
            "activation_urge": self.activation_urge,
            "exploration_urge": self.exploration_urge,
            "social_urge": self.social_urge,
            "security_need": self.security_need,
            "orientation_need": self.orientation_need,
            "residual_affect_weight": self.residual_affect_weight,
            "readiness": self.readiness,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class AwakeningState:
    phase: AwakeningLifecyclePhase
    appraisal: AwakeningAppraisal
    started_at: datetime
    phase_started_at: datetime
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        _aware("started_at", self.started_at)
        _aware("phase_started_at", self.phase_started_at)
        if self.completed_at is not None:
            _aware("completed_at", self.completed_at)
        if self.phase is AwakeningLifecyclePhase.READY and self.completed_at is None:
            raise ValueError("ready awakening state requires completed_at")
        if self.phase is not AwakeningLifecyclePhase.READY and self.completed_at is not None:
            raise ValueError("only ready awakening state may have completed_at")

    @property
    def ready(self) -> bool:
        return self.phase is AwakeningLifecyclePhase.READY

    def transition(
        self,
        phase: AwakeningLifecyclePhase,
        *,
        at: datetime,
    ) -> AwakeningState:
        _aware("at", at)
        return replace(
            self,
            phase=phase,
            phase_started_at=at,
            completed_at=(at if phase is AwakeningLifecyclePhase.READY else None),
        )

    def as_context(self) -> dict[str, object]:
        return {
            "phase": self.phase.value,
            "started_at": self.started_at.isoformat(),
            "phase_started_at": self.phase_started_at.isoformat(),
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at is not None else None
            ),
            "appraisal": self.appraisal.as_context(),
        }


__all__ = [
    "AwakeningAppraisal",
    "AwakeningLifecyclePhase",
    "AwakeningState",
]
