from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from app.domain.body import Quaternion, Vector3
from app.domain.contracts.common import require_aware, require_identifier, require_revision


class BodyTargetTrackingMode(str, Enum):
    SNAPSHOT_AT_ADMISSION = "snapshot_at_admission"
    TRACK_LATEST = "track_latest"


@dataclass(frozen=True, slots=True)
class BodySpatialTargetSnapshot:
    target_ref: str
    position: Vector3 | None
    orientation: Quaternion | None
    linear_velocity: Vector3 | None
    source_owner: str
    source_ref: str
    source_revision: int
    generation: int
    observed_at: datetime

    def __post_init__(self) -> None:
        for name in ("target_ref", "source_owner", "source_ref"):
            require_identifier(getattr(self, name), name)
        require_revision(self.source_revision, "source_revision")
        require_revision(self.generation, "generation")
        require_aware(self.observed_at, "observed_at")
        if self.position is not None and not isinstance(self.position, Vector3):
            raise ValueError("positionはVector3でなければなりません")
        if self.orientation is not None and not isinstance(self.orientation, Quaternion):
            raise ValueError("orientationはQuaternionでなければなりません")
        if self.linear_velocity is not None and not isinstance(self.linear_velocity, Vector3):
            raise ValueError("linear_velocityはVector3でなければなりません")
        if self.position is None and self.orientation is None:
            raise ValueError("target snapshotはposition又はorientationを必要とします")


class BodySpatialTargetResolverPort(Protocol):
    def resolve(self, target_ref: str) -> BodySpatialTargetSnapshot | None: ...
