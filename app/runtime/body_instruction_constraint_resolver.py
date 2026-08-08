from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from app.domain.body_instruction import BodyInstruction
from app.domain.body_pose_dynamics import (
    BodyExternalConstraint,
    BodyPoseAxis,
    BodyPoseConstraintTarget,
)


@dataclass(frozen=True, slots=True)
class BodyInstructionResolution:
    constraint: BodyExternalConstraint | None
    reason: str

    @property
    def supported(self) -> bool:
        return self.constraint is not None


class BodyInstructionConstraintResolver:
    """身体の意味指示を、モデル非依存の短時間Pose制約へ変換する。

    Raw text、モーション名、再生時刻は扱わない。既存のEmotion/Drive由来Poseを
    主状態として維持し、その上へ短時間だけ意味制約を重ねる。

    複合BodyInstructionは各componentを別々に再生せず、全componentのPose targetを
    一個のBodyExternalConstraintへ統合する。これにより「左を見ながら右手を挙げる」
    などの一つの意識的行動を同じ時間窓で満たす。
    """

    def resolve(self, instruction: BodyInstruction) -> BodyInstructionResolution:
        if not isinstance(instruction, BodyInstruction):
            raise TypeError("instruction must be BodyInstruction")
        if instruction.magnitude <= 0.0:
            return BodyInstructionResolution(None, "zero_magnitude")

        if instruction.components:
            targets = self._composite_targets(instruction.components)
            if targets is None:
                return BodyInstructionResolution(
                    None,
                    "unsupported_or_conflicting_body_instruction_component",
                )
            duration_ms = max(
                self._duration_ms(component) for component in instruction.components
            )
            reason = "body_instruction_composite_resolved"
        else:
            targets = self._targets(instruction)
            if not targets:
                return BodyInstructionResolution(None, "unsupported_body_instruction")
            duration_ms = self._duration_ms(instruction)
            reason = "body_instruction_resolved"

        constraint = BodyExternalConstraint(
            constraint_id=f"explicit-body-{uuid4()}",
            targets=targets,
            duration_ms=duration_ms,
            attack_ratio=0.16,
            release_ratio=0.28,
        )
        return BodyInstructionResolution(constraint, reason)

    def _composite_targets(
        self,
        components: tuple[BodyInstruction, ...],
    ) -> tuple[BodyPoseConstraintTarget, ...] | None:
        if not components:
            return None
        by_axis: dict[BodyPoseAxis, BodyPoseConstraintTarget] = {}
        for component in components:
            targets = self._targets(component)
            if not targets:
                return None
            for target in targets:
                current = by_axis.get(target.axis)
                if current is not None:
                    if (
                        abs(current.value - target.value) > 1e-6
                        or abs(current.weight - target.weight) > 1e-6
                    ):
                        return None
                    continue
                by_axis[target.axis] = target
        return tuple(by_axis.values())

    def _targets(
        self,
        instruction: BodyInstruction,
    ) -> tuple[BodyPoseConstraintTarget, ...]:
        effector = instruction.effector
        direction = instruction.direction
        side = instruction.side
        magnitude = instruction.magnitude

        if effector in {"head", "face", "look"}:
            horizontal = self._horizontal_look_targets(
                direction=direction,
                side=side,
                magnitude=magnitude,
            )
            vertical = self._vertical_look_targets(
                direction=direction,
                magnitude=magnitude,
            )
            if horizontal or vertical:
                return (*horizontal, *vertical)

        if effector in {"gaze", "eyes", "eye"}:
            horizontal = self._horizontal_gaze_targets(
                direction=direction,
                side=side,
                magnitude=magnitude,
            )
            vertical = self._vertical_gaze_targets(
                direction=direction,
                magnitude=magnitude,
            )
            if horizontal or vertical:
                return (*horizontal, *vertical)

        if effector in {"arm", "hand"} and side in {"left", "right"}:
            raise_axis = (
                BodyPoseAxis.LEFT_ARM_RAISE
                if side == "left"
                else BodyPoseAxis.RIGHT_ARM_RAISE
            )
            inward_axis = (
                BodyPoseAxis.LEFT_ARM_IN
                if side == "left"
                else BodyPoseAxis.RIGHT_ARM_IN
            )
            if direction in {"up", "raise", "raised"}:
                return (self._target(raise_axis, max(0.38, magnitude)),)
            if direction in {"down", "lower", "lowered"}:
                return (self._target(raise_axis, 0.0),)
            if direction in {"in", "inward"}:
                return (self._target(inward_axis, 0.78 * magnitude),)
            if direction in {"out", "outward"}:
                return (self._target(inward_axis, -0.62 * magnitude),)

        if effector in {"torso", "body", "upper_body"}:
            if direction in {"right", "left"}:
                sign = 1.0 if direction == "right" else -1.0
                return (self._target(BodyPoseAxis.TORSO_YAW, sign * 0.52 * magnitude),)
            if direction in {"forward", "front", "back", "backward"}:
                sign = 1.0 if direction in {"forward", "front"} else -1.0
                return (self._target(BodyPoseAxis.TORSO_PITCH, sign * 0.42 * magnitude),)

        return ()

    def _horizontal_look_targets(
        self,
        *,
        direction: str,
        side: str | None,
        magnitude: float,
    ) -> tuple[BodyPoseConstraintTarget, ...]:
        horizontal_direction = (
            direction if direction in {"right", "left"} else side
        )
        if horizontal_direction not in {"right", "left"}:
            return ()
        sign = 1.0 if horizontal_direction == "right" else -1.0
        return (
            self._target(BodyPoseAxis.HEAD_YAW, sign * 0.72 * magnitude),
            self._target(BodyPoseAxis.GAZE_X, sign * 0.86 * magnitude, 0.92),
        )

    def _vertical_look_targets(
        self,
        *,
        direction: str,
        magnitude: float,
    ) -> tuple[BodyPoseConstraintTarget, ...]:
        if direction not in {"up", "down"}:
            return ()
        sign = 1.0 if direction == "up" else -1.0
        return (
            self._target(BodyPoseAxis.HEAD_PITCH, sign * 0.58 * magnitude),
            self._target(BodyPoseAxis.GAZE_Y, sign * 0.76 * magnitude, 0.92),
        )

    def _horizontal_gaze_targets(
        self,
        *,
        direction: str,
        side: str | None,
        magnitude: float,
    ) -> tuple[BodyPoseConstraintTarget, ...]:
        horizontal_direction = (
            direction if direction in {"right", "left"} else side
        )
        if horizontal_direction not in {"right", "left"}:
            return ()
        sign = 1.0 if horizontal_direction == "right" else -1.0
        return (self._target(BodyPoseAxis.GAZE_X, sign * 0.88 * magnitude),)

    def _vertical_gaze_targets(
        self,
        *,
        direction: str,
        magnitude: float,
    ) -> tuple[BodyPoseConstraintTarget, ...]:
        if direction not in {"up", "down"}:
            return ()
        sign = 1.0 if direction == "up" else -1.0
        return (self._target(BodyPoseAxis.GAZE_Y, sign * 0.88 * magnitude),)

    @staticmethod
    def _target(
        axis: BodyPoseAxis,
        value: float,
        weight: float = 1.0,
    ) -> BodyPoseConstraintTarget:
        return BodyPoseConstraintTarget(axis=axis, value=value, weight=weight)

    @staticmethod
    def _duration_ms(instruction: BodyInstruction) -> int:
        if instruction.effector in {"gaze", "eyes", "eye", "head", "face", "look"}:
            return 1500
        return 1900


__all__ = ["BodyInstructionConstraintResolver", "BodyInstructionResolution"]
