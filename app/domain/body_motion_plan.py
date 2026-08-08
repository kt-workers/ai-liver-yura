from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid4

from app.domain.body_geometry import BodyGazeVector, BodyTransform3D, BodyVector3
from app.domain.body_motion_goal import BodyMotionGoal
from app.domain.body_skeleton import BodyJointPose
from app.domain.body_value_validation import (
    bounded_number,
    non_negative_integer,
    normalized_identifier,
)


class BodyMotionPhaseKind(str, Enum):
    ATTACK = "attack"
    HOLD = "hold"
    RELEASE = "release"
    PREPARE = "prepare"
    PROPEL = "propel"
    AIRBORNE = "airborne"
    LAND = "land"
    SETTLE = "settle"


@dataclass(frozen=True, slots=True)
class BodyMotionPhase:
    kind: BodyMotionPhaseKind
    start_ratio: float
    end_ratio: float

    def __post_init__(self) -> None:
        kind = self.kind
        if isinstance(kind, str):
            kind = BodyMotionPhaseKind(kind)
        if not isinstance(kind, BodyMotionPhaseKind):
            raise TypeError("kind must be BodyMotionPhaseKind")
        start = bounded_number(self.start_ratio, "start_ratio", 0.0, 1.0)
        end = bounded_number(self.end_ratio, "end_ratio", 0.0, 1.0)
        if start >= end:
            raise ValueError("start_ratio must be smaller than end_ratio")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "start_ratio", start)
        object.__setattr__(self, "end_ratio", end)

    def local_progress(self, progress: float) -> float | None:
        value = bounded_number(progress, "progress", 0.0, 1.0)
        if value < self.start_ratio or value > self.end_ratio:
            return None
        return (value - self.start_ratio) / (self.end_ratio - self.start_ratio)


@dataclass(frozen=True, slots=True)
class BodyMotionPlan:
    """高レベルGoalを実行するためのモデル非依存計画。

    完成Pose列は保持せず、Solverが毎Frame現在状態から解くGoal、使用chain、phaseだけを持つ。
    """

    goal: BodyMotionGoal
    chain_ids: tuple[str, ...]
    phases: tuple[BodyMotionPhase, ...]
    duration_ms: int
    plan_id: str = field(default_factory=lambda: f"body-plan-{uuid4()}")

    def __post_init__(self) -> None:
        if not isinstance(self.goal, BodyMotionGoal):
            raise TypeError("goal must be BodyMotionGoal")
        chain_ids = tuple(
            normalized_identifier(
                value,
                "chain_id",
                lowercase=True,
                maximum_length=80,
            )
            for value in self.chain_ids
        )
        if len(chain_ids) != len(set(chain_ids)):
            raise ValueError("chain_ids must be unique")
        phases = tuple(self.phases)
        if not phases or not all(isinstance(value, BodyMotionPhase) for value in phases):
            raise ValueError("phases must contain BodyMotionPhase values")
        ordered = sorted(phases, key=lambda value: value.start_ratio)
        if tuple(ordered) != phases:
            raise ValueError("phases must be ordered by start_ratio")
        duration = non_negative_integer(self.duration_ms, "duration_ms")
        if duration != self.goal.duration_ms:
            raise ValueError("plan duration must match goal duration")
        object.__setattr__(
            self,
            "plan_id",
            normalized_identifier(self.plan_id, "plan_id", maximum_length=128),
        )
        object.__setattr__(self, "chain_ids", chain_ids)
        object.__setattr__(self, "phases", phases)

    def phase_at(self, progress: float) -> BodyMotionPhase | None:
        value = bounded_number(progress, "progress", 0.0, 1.0)
        for phase in self.phases:
            if phase.start_ratio <= value <= phase.end_ratio:
                return phase
        return None


class BodyMotionExecutionStatus(str, Enum):
    ACCEPTED = "accepted"
    PLANNED = "planned"
    STARTED = "started"
    OBSERVABLE = "observable"
    COMPLETED = "completed"
    REJECTED = "rejected"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class BodyMotionExecutionResult:
    status: BodyMotionExecutionStatus
    goal_id: str
    plan_id: str | None
    reason: str

    def __post_init__(self) -> None:
        status = self.status
        if isinstance(status, str):
            status = BodyMotionExecutionStatus(status)
        if not isinstance(status, BodyMotionExecutionStatus):
            raise TypeError("status must be BodyMotionExecutionStatus")
        object.__setattr__(self, "status", status)
        object.__setattr__(
            self,
            "goal_id",
            normalized_identifier(self.goal_id, "goal_id", maximum_length=128),
        )
        if self.plan_id is not None:
            object.__setattr__(
                self,
                "plan_id",
                normalized_identifier(self.plan_id, "plan_id", maximum_length=128),
            )
        object.__setattr__(
            self,
            "reason",
            normalized_identifier(self.reason, "reason", maximum_length=240),
        )

    @property
    def accepted(self) -> bool:
        return self.status not in {
            BodyMotionExecutionStatus.REJECTED,
            BodyMotionExecutionStatus.UNSUPPORTED,
        }


@dataclass(frozen=True, slots=True)
class BodyGenerativeMotionSample:
    """1 tick分の3D Motion出力。BodyPoseFrameの3D主契約へ合成する。"""

    plan_id: str
    progress: float
    root_transform: BodyTransform3D
    joints: tuple[BodyJointPose, ...]
    gaze_vector: BodyGazeVector
    phase: BodyMotionPhaseKind | None = None
    affected_joint_ids: tuple[str, ...] = ()
    compatibility_axes: tuple[tuple[str, float], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "plan_id",
            normalized_identifier(self.plan_id, "plan_id", maximum_length=128),
        )
        object.__setattr__(
            self,
            "progress",
            bounded_number(self.progress, "progress", 0.0, 1.0),
        )
        if not isinstance(self.root_transform, BodyTransform3D):
            raise TypeError("root_transform must be BodyTransform3D")
        joints = tuple(self.joints)
        if not all(isinstance(value, BodyJointPose) for value in joints):
            raise TypeError("joints must contain BodyJointPose values")
        joint_ids = [value.joint_id for value in joints]
        if len(joint_ids) != len(set(joint_ids)):
            raise ValueError("sample joint ids must be unique")
        if not isinstance(self.gaze_vector, BodyGazeVector):
            raise TypeError("gaze_vector must be BodyGazeVector")
        phase = self.phase
        if isinstance(phase, str):
            phase = BodyMotionPhaseKind(phase)
        if phase is not None and not isinstance(phase, BodyMotionPhaseKind):
            raise TypeError("phase must be BodyMotionPhaseKind or None")
        affected = tuple(
            normalized_identifier(value, "joint_id", lowercase=True, maximum_length=80)
            for value in self.affected_joint_ids
        )
        axes = tuple((str(name), float(value)) for name, value in self.compatibility_axes)
        object.__setattr__(self, "joints", joints)
        object.__setattr__(self, "phase", phase)
        object.__setattr__(self, "affected_joint_ids", affected)
        object.__setattr__(self, "compatibility_axes", axes)

    def compatibility_axis_map(self) -> dict[str, float]:
        return dict(self.compatibility_axes)


__all__ = [
    "BodyGenerativeMotionSample",
    "BodyMotionExecutionResult",
    "BodyMotionExecutionStatus",
    "BodyMotionPhase",
    "BodyMotionPhaseKind",
    "BodyMotionPlan",
]
