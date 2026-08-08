from __future__ import annotations

from app.domain.body_motion_goal import BodyMotionGoal, BodyMotionGoalKind
from app.domain.body_motion_plan import (
    BodyMotionPhase,
    BodyMotionPhaseKind,
    BodyMotionPlan,
)
from app.domain.body_skeleton_profile import BodySkeletonProfile


class BodyMotionPlanner:
    """高レベルBodyMotionGoalをSkeleton依存の計画へ変換する。

    完成Pose列は作らず、使用chainと時間phaseだけを決める。関節角は
    Kinematic Solverが現在状態から毎Frame解く。
    """

    def __init__(self, skeleton: BodySkeletonProfile | None = None) -> None:
        self._skeleton = skeleton or BodySkeletonProfile.canonical_humanoid()

    @property
    def skeleton(self) -> BodySkeletonProfile:
        return self._skeleton

    def plan(self, goal: BodyMotionGoal) -> BodyMotionPlan:
        if not isinstance(goal, BodyMotionGoal):
            raise TypeError("goal must be BodyMotionGoal")
        chain_ids = self._chain_ids(goal)
        phases = self._phases(goal.kind)
        return BodyMotionPlan(
            goal=goal,
            chain_ids=chain_ids,
            phases=phases,
            duration_ms=goal.duration_ms,
        )

    def _chain_ids(self, goal: BodyMotionGoal) -> tuple[str, ...]:
        if goal.kind is BodyMotionGoalKind.COMPOSITE:
            ordered: list[str] = []
            for component in goal.components:
                for chain_id in self._chain_ids(component):
                    if chain_id not in ordered:
                        ordered.append(chain_id)
            return tuple(ordered)

        if goal.kind is BodyMotionGoalKind.END_EFFECTOR_POSITION:
            assert goal.target_id is not None
            return (self._skeleton.chain_for_end_effector(goal.target_id).chain_id,)

        if goal.kind is BodyMotionGoalKind.LOOK_DIRECTION:
            return ("head",)

        if goal.kind is BodyMotionGoalKind.JOINT_ORIENTATION:
            assert goal.target_id is not None
            chains = tuple(
                value.chain_id
                for value in self._skeleton.chains
                if goal.target_id in value.joint_ids
            )
            return chains

        if goal.kind is BodyMotionGoalKind.ROOT_TRANSLATION:
            return ("left_leg", "right_leg", "head")

        if goal.kind in {BodyMotionGoalKind.CROUCH, BodyMotionGoalKind.JUMP}:
            return ("left_leg", "right_leg", "head")

        if goal.kind is BodyMotionGoalKind.OSCILLATE:
            assert goal.target_id is not None
            try:
                return (self._skeleton.chain_for_end_effector(goal.target_id).chain_id,)
            except KeyError:
                return tuple(
                    value.chain_id
                    for value in self._skeleton.chains
                    if goal.target_id in value.joint_ids
                )

        return ()

    @staticmethod
    def _phases(kind: BodyMotionGoalKind) -> tuple[BodyMotionPhase, ...]:
        phase = BodyMotionPhase
        k = BodyMotionPhaseKind
        if kind is BodyMotionGoalKind.JUMP:
            return (
                phase(k.PREPARE, 0.00, 0.20),
                phase(k.PROPEL, 0.20, 0.34),
                phase(k.AIRBORNE, 0.34, 0.68),
                phase(k.LAND, 0.68, 0.84),
                phase(k.SETTLE, 0.84, 1.00),
            )
        return (
            phase(k.ATTACK, 0.00, 0.24),
            phase(k.HOLD, 0.24, 0.72),
            phase(k.RELEASE, 0.72, 1.00),
        )


__all__ = ["BodyMotionPlanner"]
