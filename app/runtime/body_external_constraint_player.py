from __future__ import annotations

from dataclasses import dataclass

from app.domain.body_pose_dynamics import (
    BodyExternalConstraint,
    BodyPoseConstraintTarget,
)

_COMPLETION_EPSILON_SECONDS = 1e-9


def _smoothstep(value: float) -> float:
    normalized = max(0.0, min(1.0, value))
    return normalized * normalized * (3.0 - 2.0 * normalized)


@dataclass(frozen=True, slots=True)
class BodyExternalConstraintSample:
    constraint_id: str | None
    targets: tuple[BodyPoseConstraintTarget, ...]
    envelope: float
    completed: bool = False


class BodyExternalConstraintPlayer:
    """意味解決済み外部制約のattack／hold／releaseだけを管理する。"""

    def __init__(self) -> None:
        self._active: BodyExternalConstraint | None = None
        self._elapsed = 0.0

    @property
    def active_constraint_id(self) -> str | None:
        return self._active.constraint_id if self._active is not None else None

    def apply(self, constraint: BodyExternalConstraint) -> None:
        if not isinstance(constraint, BodyExternalConstraint):
            raise TypeError("constraint must be BodyExternalConstraint")
        self._active = constraint
        self._elapsed = 0.0

    def clear(self) -> None:
        self._active = None
        self._elapsed = 0.0

    def step(self, *, dt_seconds: float) -> BodyExternalConstraintSample:
        constraint = self._active
        if constraint is None:
            return BodyExternalConstraintSample(None, (), 0.0)

        dt = max(1.0 / 240.0, min(0.1, float(dt_seconds)))
        duration = constraint.duration_ms / 1000.0
        next_elapsed = self._elapsed + dt
        completed = next_elapsed + _COMPLETION_EPSILON_SECONDS >= duration
        self._elapsed = duration if completed else next_elapsed
        progress = self._elapsed / duration
        sample = BodyExternalConstraintSample(
            constraint_id=constraint.constraint_id,
            targets=constraint.targets,
            envelope=0.0 if completed else self._envelope(constraint, progress),
            completed=completed,
        )
        if completed:
            self.clear()
        return sample

    @staticmethod
    def _envelope(constraint: BodyExternalConstraint, progress: float) -> float:
        if constraint.attack_ratio > 0.0 and progress < constraint.attack_ratio:
            return _smoothstep(progress / constraint.attack_ratio)
        release_start = 1.0 - constraint.release_ratio
        if constraint.release_ratio > 0.0 and progress > release_start:
            return _smoothstep((1.0 - progress) / constraint.release_ratio)
        return 1.0
