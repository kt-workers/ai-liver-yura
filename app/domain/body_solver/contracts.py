from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite

from app.domain.body_motion_planning import BodyBalanceMode, BodySpatialTarget
from app.domain.contracts.common import require_identifier, require_revision


class BodySolveTaskKind(str, Enum):
    ORIENTATION_TARGET = "orientation_target"
    POSITION_TARGET = "position_target"
    CONTACT_TARGET = "contact_target"
    ROOT_IMPULSE_TARGET = "root_impulse_target"


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
