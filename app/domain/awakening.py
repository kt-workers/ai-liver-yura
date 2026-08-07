from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

AWAKENING_SNAPSHOT_SCHEMA_VERSION = 1


class AwakeningStartupKind(str, Enum):
    COLD_START = "cold_start"
    RESUME = "resume"
    RESTART = "restart"


class AwakeningSnapshotLoadStatus(str, Enum):
    LOADED = "loaded"
    MISSING = "missing"
    CORRUPT = "corrupt"
    VERSION_MISMATCH = "version_mismatch"
    IO_ERROR = "io_error"


def _bounded(name: str, value: float, minimum: float, maximum: float) -> float:
    normalized = float(value)
    if not math.isfinite(normalized) or not minimum <= normalized <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return normalized


def _aware_datetime(name: str, value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class AwakeningEmotionSnapshot:
    mood: str
    arousal: float
    valence: float
    talkativeness: float
    joy: float = 0.0
    amusement: float = 0.0
    anger: float = 0.0
    sadness: float = 0.0
    fear: float = 0.0
    surprise: float = 0.0
    discomfort: float = 0.0
    emotional_pressure: float = 0.0

    def __post_init__(self) -> None:
        mood = self.mood.strip()
        if not mood:
            raise ValueError("mood must not be empty")
        object.__setattr__(self, "mood", mood[:32])
        object.__setattr__(self, "arousal", _bounded("arousal", self.arousal, 0.0, 1.0))
        object.__setattr__(self, "valence", _bounded("valence", self.valence, -1.0, 1.0))
        object.__setattr__(self, "talkativeness", _bounded("talkativeness", self.talkativeness, 0.0, 1.0))
        for name in (
            "joy", "amusement", "anger", "sadness", "fear", "surprise",
            "discomfort", "emotional_pressure",
        ):
            object.__setattr__(self, name, _bounded(name, getattr(self, name), 0.0, 1.0))

    def as_context(self) -> dict[str, object]:
        return {
            "mood": self.mood,
            "arousal": self.arousal,
            "valence": self.valence,
            "talkativeness": self.talkativeness,
            "reactive": {
                "joy": self.joy,
                "amusement": self.amusement,
                "anger": self.anger,
                "sadness": self.sadness,
                "fear": self.fear,
                "surprise": self.surprise,
                "discomfort": self.discomfort,
                "emotional_pressure": self.emotional_pressure,
            },
        }


@dataclass(frozen=True, slots=True)
class AwakeningDriveSnapshot:
    curiosity: float
    engagement: float
    boredom: float
    energy: float

    def __post_init__(self) -> None:
        for name in ("curiosity", "engagement", "boredom", "energy"):
            object.__setattr__(self, name, _bounded(name, getattr(self, name), 0.0, 1.0))

    def as_context(self) -> dict[str, float]:
        return {
            "curiosity": self.curiosity,
            "engagement": self.engagement,
            "boredom": self.boredom,
            "energy": self.energy,
        }


@dataclass(frozen=True, slots=True)
class AwakeningDesireSnapshot:
    connection: float
    curiosity: float
    expression: float
    recognition: float
    autonomy: float
    security: float
    achievement: float

    def __post_init__(self) -> None:
        for name in (
            "connection", "curiosity", "expression", "recognition", "autonomy",
            "security", "achievement",
        ):
            object.__setattr__(self, name, _bounded(name, getattr(self, name), 0.0, 1.0))

    def as_context(self) -> dict[str, float]:
        return {
            "connection": self.connection,
            "curiosity": self.curiosity,
            "expression": self.expression,
            "recognition": self.recognition,
            "autonomy": self.autonomy,
            "security": self.security,
            "achievement": self.achievement,
        }


@dataclass(frozen=True, slots=True)
class AwakeningInnerStateSnapshot:
    emotion: AwakeningEmotionSnapshot
    drive: AwakeningDriveSnapshot
    desire: AwakeningDesireSnapshot

    def as_context(self) -> dict[str, object]:
        return {
            "emotion": self.emotion.as_context(),
            "drive": self.drive.as_context(),
            "desire": self.desire.as_context(),
        }


@dataclass(frozen=True, slots=True)
class AwakeningSnapshot:
    shutdown_at: datetime
    inner_state: AwakeningInnerStateSnapshot
    schema_version: int = AWAKENING_SNAPSHOT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _aware_datetime("shutdown_at", self.shutdown_at)
        if self.schema_version != AWAKENING_SNAPSHOT_SCHEMA_VERSION:
            raise ValueError("unsupported awakening snapshot schema version")

    def as_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "shutdown_at": self.shutdown_at.isoformat(),
            "inner_state": self.inner_state.as_context(),
        }


@dataclass(frozen=True, slots=True)
class AwakeningSnapshotLoadResult:
    status: AwakeningSnapshotLoadStatus
    snapshot: AwakeningSnapshot | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        if self.status is AwakeningSnapshotLoadStatus.LOADED and self.snapshot is None:
            raise ValueError("loaded result requires snapshot")
        if self.status is not AwakeningSnapshotLoadStatus.LOADED and self.snapshot is not None:
            raise ValueError("non-loaded result must not contain snapshot")
        object.__setattr__(self, "reason", self.reason.strip()[:160])


@dataclass(frozen=True, slots=True)
class AwakeningCapabilities:
    body_available: bool
    tts_available: bool
    conversation_output_available: bool

    def as_context(self) -> dict[str, bool]:
        return {
            "body_available": self.body_available,
            "tts_available": self.tts_available,
            "conversation_output_available": self.conversation_output_available,
        }


@dataclass(frozen=True, slots=True)
class AwakeningContext:
    startup_kind: AwakeningStartupKind
    started_at: datetime
    capabilities: AwakeningCapabilities
    persistence_status: AwakeningSnapshotLoadStatus
    previous_shutdown_at: datetime | None = None
    downtime_seconds: float | None = None
    previous_inner_state: AwakeningInnerStateSnapshot | None = None
    persistence_reason: str = ""

    def __post_init__(self) -> None:
        _aware_datetime("started_at", self.started_at)
        if self.previous_shutdown_at is not None:
            _aware_datetime("previous_shutdown_at", self.previous_shutdown_at)
        if self.downtime_seconds is not None:
            value = float(self.downtime_seconds)
            if not math.isfinite(value) or value < 0.0:
                raise ValueError("downtime_seconds must be finite and non-negative")
            object.__setattr__(self, "downtime_seconds", value)
        object.__setattr__(self, "persistence_reason", self.persistence_reason.strip()[:160])

    def as_context(self) -> dict[str, object]:
        return {
            "startup_kind": self.startup_kind.value,
            "started_at": self.started_at.isoformat(),
            "previous_shutdown_at": (
                self.previous_shutdown_at.isoformat()
                if self.previous_shutdown_at is not None
                else None
            ),
            "downtime_seconds": self.downtime_seconds,
            "previous_inner_state": (
                self.previous_inner_state.as_context()
                if self.previous_inner_state is not None
                else None
            ),
            "capabilities": self.capabilities.as_context(),
            "persistence_status": self.persistence_status.value,
            "persistence_reason": self.persistence_reason,
        }


__all__ = [
    "AWAKENING_SNAPSHOT_SCHEMA_VERSION",
    "AwakeningCapabilities",
    "AwakeningContext",
    "AwakeningDesireSnapshot",
    "AwakeningDriveSnapshot",
    "AwakeningEmotionSnapshot",
    "AwakeningInnerStateSnapshot",
    "AwakeningSnapshot",
    "AwakeningSnapshotLoadResult",
    "AwakeningSnapshotLoadStatus",
    "AwakeningStartupKind",
]
