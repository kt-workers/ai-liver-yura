from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite

from app.domain.body import BodyPose, BodyVelocity
from app.domain.body_motion_planning import BodyBalanceMode, BodySpatialTarget
from app.domain.body_realtime.contracts import RealtimeChannel
from app.domain.contracts.common import (
    require_aware,
    require_identifier,
    require_revision,
    timestamp_to_json,
)


class BodySolveTaskKind(str, Enum):
    ORIENTATION_TARGET = "orientation_target"
    POSITION_TARGET = "position_target"
    CONTACT_TARGET = "contact_target"
    ROOT_IMPULSE_TARGET = "root_impulse_target"


class BodyMotionExecutionStatus(str, Enum):
    PLANNED = "planned"
    STARTED = "started"
    OBSERVABLE = "observable"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    SUPERSEDED = "superseded"
    INFEASIBLE = "infeasible"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


class BodySolverFailureCode(str, Enum):
    INVALID_PLAN = "invalid_plan"
    MODEL_MISMATCH = "model_mismatch"
    UNKNOWN_BODY_REFERENCE = "unknown_body_reference"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    INFEASIBLE_TARGET = "infeasible_target"
    HARD_LIMIT_CONFLICT = "hard_limit_conflict"
    BALANCE_INFEASIBLE = "balance_infeasible"
    CONTACT_INFEASIBLE = "contact_infeasible"
    NUMERICAL_FAILURE = "numerical_failure"
    STALE_HARD_DEPENDENCY = "stale_hard_dependency"
    CANCELLED = "cancelled"


def _duration(value: float, name: str) -> float:
    if type(value) not in (int, float) or not isfinite(value) or value <= 0:
        raise ValueError(f"{name} は正の有限秒数でなければなりません")
    return float(value)


def _nonnegative(value: float, name: str) -> float:
    if type(value) not in (int, float) or not isfinite(value) or value < 0:
        raise ValueError(f"{name} は0以上の有限秒数でなければなりません")
    return float(value)


def _identifiers(values: tuple[str, ...], name: str, *, non_empty: bool = True) -> tuple[str, ...]:
    if not isinstance(values, tuple) or (non_empty and not values):
        raise ValueError(f"{name} は正しい tuple でなければなりません")
    for value in values:
        require_identifier(value, name)
    if len(values) != len(set(values)):
        raise ValueError(f"{name} は一意でなければなりません")
    return values


def _signed_unit(value: float, name: str) -> float:
    if type(value) not in (int, float) or not isfinite(value) or not -1 <= value <= 1:
        raise ValueError(f"{name} は有限の [-1, 1] でなければなりません")
    return float(value)


@dataclass(frozen=True, slots=True)
class BodySolveTask:
    goal_id: str
    kind: BodySolveTaskKind
    joint_ids: tuple[str, ...]
    chain_ids: tuple[str, ...]
    spatial_target: BodySpatialTarget | None
    intensity: float

    def __post_init__(self) -> None:
        require_identifier(self.goal_id, "goal_id")
        if not isinstance(self.kind, BodySolveTaskKind):
            raise ValueError("kind が不正です")
        object.__setattr__(self, "joint_ids", _identifiers(self.joint_ids, "joint_ids"))
        object.__setattr__(self, "chain_ids", _identifiers(self.chain_ids, "chain_ids"))
        if self.spatial_target is not None and not isinstance(
            self.spatial_target, BodySpatialTarget
        ):
            raise ValueError("spatial_target が不正です")
        if type(self.intensity) not in (int, float) or not isfinite(self.intensity):
            raise ValueError("intensity は有限値でなければなりません")
        if not 0 <= self.intensity <= 1:
            raise ValueError("intensity は [0, 1] でなければなりません")
        object.__setattr__(self, "intensity", float(self.intensity))


@dataclass(frozen=True, slots=True)
class BodyTrajectoryPhase:
    phase_id: str
    start_offset_s: float
    end_offset_s: float
    tasks: tuple[BodySolveTask, ...]
    balance_mode: BodyBalanceMode

    def __post_init__(self) -> None:
        require_identifier(self.phase_id, "phase_id")
        object.__setattr__(
            self, "start_offset_s", _nonnegative(self.start_offset_s, "start_offset_s")
        )
        object.__setattr__(self, "end_offset_s", _duration(self.end_offset_s, "end_offset_s"))
        if self.start_offset_s < 0 or self.end_offset_s <= self.start_offset_s:
            raise ValueError("phase の時刻区間が不正です")
        if not isinstance(self.tasks, tuple) or not self.tasks:
            raise ValueError("tasks は空にできません")
        if any(not isinstance(task, BodySolveTask) for task in self.tasks):
            raise ValueError("tasks が不正です")
        if not isinstance(self.balance_mode, BodyBalanceMode):
            raise ValueError("balance_mode が不正です")


@dataclass(frozen=True, slots=True)
class ExecutableBodyTrajectory:
    trajectory_id: str
    plan_id: str
    body_model_id: str
    start_body_state_revision: int
    involved_joint_ids: tuple[str, ...]
    involved_chain_ids: tuple[str, ...]
    phases: tuple[BodyTrajectoryPhase, ...]

    def __post_init__(self) -> None:
        for name in ("trajectory_id", "plan_id", "body_model_id"):
            require_identifier(getattr(self, name), name)
        require_revision(self.start_body_state_revision, "start_body_state_revision")
        object.__setattr__(
            self,
            "involved_joint_ids",
            _identifiers(self.involved_joint_ids, "involved_joint_ids"),
        )
        object.__setattr__(
            self,
            "involved_chain_ids",
            _identifiers(self.involved_chain_ids, "involved_chain_ids", non_empty=False),
        )
        if not isinstance(self.phases, tuple) or not self.phases:
            raise ValueError("phases は空にできません")
        if any(not isinstance(phase, BodyTrajectoryPhase) for phase in self.phases):
            raise ValueError("phases が不正です")
        if tuple(sorted(phase.phase_id for phase in self.phases)) != tuple(
            sorted(set(phase.phase_id for phase in self.phases))
        ):
            raise ValueError("phase_id は一意でなければなりません")
        previous_end = 0.0
        for phase in self.phases:
            if phase.start_offset_s != previous_end:
                raise ValueError("phase は連続していなければなりません")
            previous_end = phase.end_offset_s


@dataclass(frozen=True, slots=True)
class BodyFrameChannelValue:
    channel: RealtimeChannel
    value: float

    def __post_init__(self) -> None:
        if not isinstance(self.channel, RealtimeChannel):
            raise ValueError("channel が不正です")
        signed = self.channel in {
            RealtimeChannel.GAZE_X,
            RealtimeChannel.GAZE_Y,
            RealtimeChannel.MOUTH_ROUNDNESS,
            RealtimeChannel.SUBTLE_SWAY,
        }
        normalized = _signed_unit(self.value, "value")
        if not signed and normalized < 0:
            raise ValueError("このchannelは負値を持てません")
        object.__setattr__(self, "value", normalized)

    def to_dict(self) -> dict[str, object]:
        return {"channel": self.channel.value, "value": self.value}


@dataclass(frozen=True, slots=True)
class BodyPoseFrame:
    frame_id: str
    body_model_id: str
    body_state_revision: int
    observed_at: datetime
    pose: BodyPose
    velocity: BodyVelocity
    active_plan_id: str | None
    active_trajectory_id: str | None
    channel_values: tuple[BodyFrameChannelValue, ...]
    applied_overlay_refs: tuple[str, ...]
    degraded_overlay_refs: tuple[str, ...]
    trace_id: str

    def __post_init__(self) -> None:
        for name in ("frame_id", "body_model_id", "trace_id"):
            require_identifier(getattr(self, name), name)
        require_revision(self.body_state_revision, "body_state_revision")
        require_aware(self.observed_at, "observed_at")
        if not isinstance(self.pose, BodyPose) or not isinstance(self.velocity, BodyVelocity):
            raise ValueError("pose / velocity が不正です")
        for name in ("active_plan_id", "active_trajectory_id"):
            value = getattr(self, name)
            if value is not None:
                require_identifier(value, name)
        channels = tuple(self.channel_values)
        if any(not isinstance(item, BodyFrameChannelValue) for item in channels):
            raise ValueError("channel_values が不正です")
        if len({item.channel for item in channels}) != len(channels):
            raise ValueError("canonical channel は一意でなければなりません")
        object.__setattr__(self, "channel_values", channels)
        applied = _identifiers(
            tuple(self.applied_overlay_refs),
            "applied_overlay_refs",
            non_empty=False,
        )
        degraded = _identifiers(
            tuple(self.degraded_overlay_refs), "degraded_overlay_refs", non_empty=False
        )
        if set(applied) & set(degraded):
            raise ValueError("overlay refをappliedとdegradedへ同時に記録できません")
        object.__setattr__(self, "applied_overlay_refs", applied)
        object.__setattr__(self, "degraded_overlay_refs", degraded)

    def to_dict(self) -> dict[str, object]:
        return {
            "frame_id": self.frame_id,
            "body_model_id": self.body_model_id,
            "body_state_revision": self.body_state_revision,
            "observed_at": timestamp_to_json(self.observed_at),
            "pose": self.pose.to_dict(),
            "velocity": self.velocity.to_dict(),
            "active_plan_id": self.active_plan_id,
            "active_trajectory_id": self.active_trajectory_id,
            "channel_values": [item.to_dict() for item in self.channel_values],
            "applied_overlay_refs": list(self.applied_overlay_refs),
            "degraded_overlay_refs": list(self.degraded_overlay_refs),
            "trace_id": self.trace_id,
        }


@dataclass(frozen=True, slots=True)
class BodyMotionResidual:
    target_ref: str
    residual: float

    def __post_init__(self) -> None:
        require_identifier(self.target_ref, "target_ref")
        if (
            type(self.residual) not in (int, float)
            or not isfinite(self.residual)
            or self.residual < 0
        ):
            raise ValueError("residual は0以上の有限値でなければなりません")
        object.__setattr__(self, "residual", float(self.residual))

    def to_dict(self) -> dict[str, object]:
        return {"target_ref": self.target_ref, "residual": self.residual}


@dataclass(frozen=True, slots=True)
class BodyMotionExecutionReport:
    plan_id: str
    trajectory_id: str
    status: BodyMotionExecutionStatus
    started_at: datetime | None = None
    observable_at: datetime | None = None
    completed_at: datetime | None = None
    achieved_target_refs: tuple[str, ...] = ()
    residuals: tuple[BodyMotionResidual, ...] = ()
    failure_code: BodySolverFailureCode | None = None

    def __post_init__(self) -> None:
        require_identifier(self.plan_id, "plan_id")
        require_identifier(self.trajectory_id, "trajectory_id")
        if not isinstance(self.status, BodyMotionExecutionStatus):
            raise ValueError("status が不正です")
        for name in ("started_at", "observable_at", "completed_at"):
            value = getattr(self, name)
            if value is not None:
                require_aware(value, name)
        if self.observable_at is not None and self.started_at is None:
            raise ValueError("OBSERVABLE時刻にはstarted_atが必要です")
        if self.completed_at is not None and self.started_at is None:
            raise ValueError("terminal時刻にはstarted_atが必要です")
        if self.status is BodyMotionExecutionStatus.PLANNED and any(
            value is not None for value in (self.started_at, self.observable_at, self.completed_at)
        ):
            raise ValueError("PLANNEDはactual時刻を持てません")
        if self.status in {
            BodyMotionExecutionStatus.STARTED,
            BodyMotionExecutionStatus.OBSERVABLE,
            BodyMotionExecutionStatus.COMPLETED,
            BodyMotionExecutionStatus.INTERRUPTED,
            BodyMotionExecutionStatus.SUPERSEDED,
        } and self.started_at is None:
            raise ValueError("actual motion statusにはstarted_atが必要です")
        if self.status is BodyMotionExecutionStatus.OBSERVABLE and self.observable_at is None:
            raise ValueError("OBSERVABLEにはobservable_atが必要です")
        if self.status is BodyMotionExecutionStatus.COMPLETED and self.completed_at is None:
            raise ValueError("COMPLETEDにはcompleted_atが必要です")
        failure_statuses = {
            BodyMotionExecutionStatus.INFEASIBLE,
            BodyMotionExecutionStatus.UNSUPPORTED,
            BodyMotionExecutionStatus.FAILED,
        }
        if self.status in failure_statuses and self.failure_code is None:
            raise ValueError("failure statusにはfailure_codeが必要です")
        if self.status not in failure_statuses and self.failure_code is not None:
            raise ValueError("非failure statusはfailure_codeを持てません")
        targets = _identifiers(
            tuple(self.achieved_target_refs),
            "achieved_target_refs",
            non_empty=False,
        )
        residuals = tuple(self.residuals)
        if any(not isinstance(item, BodyMotionResidual) for item in residuals):
            raise ValueError("residuals が不正です")
        if len({item.target_ref for item in residuals}) != len(residuals):
            raise ValueError("residual targetは一意でなければなりません")
        object.__setattr__(self, "achieved_target_refs", targets)
        object.__setattr__(self, "residuals", residuals)

    def to_dict(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "trajectory_id": self.trajectory_id,
            "status": self.status.value,
            "started_at": None if self.started_at is None else timestamp_to_json(self.started_at),
            "observable_at": (
                None if self.observable_at is None else timestamp_to_json(self.observable_at)
            ),
            "completed_at": (
                None if self.completed_at is None else timestamp_to_json(self.completed_at)
            ),
            "achieved_target_refs": list(self.achieved_target_refs),
            "residuals": [item.to_dict() for item in self.residuals],
            "failure_code": None if self.failure_code is None else self.failure_code.value,
        }
