from __future__ import annotations

import math
from dataclasses import dataclass

from app.domain.body_kinematics import (
    BodyKinematicPoint,
    GenerativeBodyPoseFrame,
)
from app.domain.body_motion import (
    BodyMotionEasing,
    BodyMotionOperation,
    BodyMotionPlan,
    BodyMotionRequest,
)
from app.domain.body_pose_frame import BodyTrackingPose
from app.runtime.body_kinematic_projector import BodyKinematicProjector
from app.runtime.body_motion_planner import BodyMotionPlanner
from app.runtime.procedural_body_controller import ProceduralBodyController


@dataclass(slots=True)
class _ActiveBodyMotion:
    plan: BodyMotionPlan
    started_at: float


class GenerativeBodyMotionController(ProceduralBodyController):
    """BodyMotionPlanを毎TickのCanonical関節位置へ展開する。

    名前付きモーションを再生せず、reach／translate／rotate／circle等を
    現在姿勢へ合成する。棒人間・Live2D・3Dは同じkinematic_poseを投影する。
    """

    _DESCENDANTS: dict[str, tuple[str, ...]] = {
        "root": (
            "pelvis",
            "spine",
            "chest",
            "neck",
            "head",
            "left_shoulder",
            "left_elbow",
            "left_hand",
            "right_shoulder",
            "right_elbow",
            "right_hand",
            "left_hip",
            "left_knee",
            "left_ankle",
            "right_hip",
            "right_knee",
            "right_ankle",
        ),
        "pelvis": (
            "pelvis",
            "spine",
            "chest",
            "neck",
            "head",
            "left_shoulder",
            "left_elbow",
            "left_hand",
            "right_shoulder",
            "right_elbow",
            "right_hand",
            "left_hip",
            "left_knee",
            "left_ankle",
            "right_hip",
            "right_knee",
            "right_ankle",
        ),
        "spine": (
            "spine",
            "chest",
            "neck",
            "head",
            "left_shoulder",
            "left_elbow",
            "left_hand",
            "right_shoulder",
            "right_elbow",
            "right_hand",
        ),
        "chest": (
            "chest",
            "neck",
            "head",
            "left_shoulder",
            "left_elbow",
            "left_hand",
            "right_shoulder",
            "right_elbow",
            "right_hand",
        ),
        "neck": ("neck", "head"),
        "head": ("head",),
        "left_shoulder": ("left_shoulder", "left_elbow", "left_hand"),
        "left_elbow": ("left_elbow", "left_hand"),
        "left_hand": ("left_hand",),
        "right_shoulder": ("right_shoulder", "right_elbow", "right_hand"),
        "right_elbow": ("right_elbow", "right_hand"),
        "right_hand": ("right_hand",),
        "left_hip": ("left_hip", "left_knee", "left_ankle"),
        "left_knee": ("left_knee", "left_ankle"),
        "left_ankle": ("left_ankle",),
        "right_hip": ("right_hip", "right_knee", "right_ankle"),
        "right_knee": ("right_knee", "right_ankle"),
        "right_ankle": ("right_ankle",),
    }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._motion_planner = BodyMotionPlanner()
        self._kinematic_projector = BodyKinematicProjector()
        self._active_motions: list[_ActiveBodyMotion] = []
        self._held_positions: dict[str, BodyKinematicPoint] = {}
        self._motion_clock = 0.0
        self._last_motion_timestamp_ms: int | None = None
        self._smoothed_positions: dict[str, BodyKinematicPoint] = {}
        self._latest_kinematic = self._kinematic_projector.project(BodyTrackingPose())

    @property
    def active_motion_ids(self) -> tuple[str, ...]:
        return tuple(active.plan.plan_id for active in self._active_motions)

    @property
    def held_targets(self) -> tuple[str, ...]:
        return tuple(sorted(self._held_positions))

    def submit_motion(self, request: BodyMotionRequest) -> BodyMotionPlan:
        plan = self._motion_planner.compile(request)
        if request.operation is BodyMotionOperation.HOLD:
            self._capture_hold(request.target)
            return plan
        if request.operation is BodyMotionOperation.RELEASE:
            self._release_hold(request.target)
            return plan
        self._active_motions.append(
            _ActiveBodyMotion(plan=plan, started_at=self._motion_clock)
        )
        return plan

    def cancel_motion(self, plan_id: str) -> bool:
        normalized = plan_id.strip()
        before = len(self._active_motions)
        self._active_motions = [
            active
            for active in self._active_motions
            if active.plan.plan_id != normalized
        ]
        return len(self._active_motions) != before

    def clear_motions(self, *, release_holds: bool = False) -> None:
        self._active_motions.clear()
        if release_holds:
            self._held_positions.clear()

    def tick(
        self,
        *,
        timestamp_ms: int | None = None,
        dt_seconds: float | None = None,
    ) -> GenerativeBodyPoseFrame:
        dt = self._motion_dt(timestamp_ms=timestamp_ms, dt_seconds=dt_seconds)
        base_frame = super().tick(
            timestamp_ms=timestamp_ms,
            dt_seconds=dt_seconds,
        )
        self._motion_clock += dt
        base_kinematic = self._kinematic_projector.project(base_frame.pose)
        base_positions = base_kinematic.positions()
        base_positions["root"] = base_kinematic.root_position
        positions = dict(base_positions)

        for target, held in self._held_positions.items():
            if target in positions:
                positions[target] = held

        completed: list[_ActiveBodyMotion] = []
        for active in self._active_motions:
            elapsed = max(0.0, self._motion_clock - active.started_at)
            self._apply_request(
                active.plan.root,
                elapsed,
                positions,
                base_positions,
            )
            if elapsed >= active.plan.duration_seconds:
                completed.append(active)

        self._solve_limbs(positions, base_positions)

        for active in completed:
            self._capture_hold_final_targets(active.plan.root, positions)
        if completed:
            completed_ids = {active.plan.plan_id for active in completed}
            self._active_motions = [
                active
                for active in self._active_motions
                if active.plan.plan_id not in completed_ids
            ]

        smoothed = self._smooth_positions(positions, dt)
        root = smoothed.pop("root")
        kinematic_pose = base_kinematic.with_positions(
            smoothed,
            root_position=root,
        )
        self._latest_kinematic = kinematic_pose
        return GenerativeBodyPoseFrame(
            base_frame=base_frame,
            kinematic_pose=kinematic_pose,
            active_motion_ids=self.active_motion_ids,
            held_targets=self.held_targets,
        )

    def _motion_dt(
        self,
        *,
        timestamp_ms: int | None,
        dt_seconds: float | None,
    ) -> float:
        if dt_seconds is not None:
            return max(1.0 / 240.0, min(0.1, float(dt_seconds)))
        if timestamp_ms is not None and self._last_motion_timestamp_ms is not None:
            dt = (timestamp_ms - self._last_motion_timestamp_ms) / 1000.0
        else:
            dt = 1.0 / self.tick_hz
        if timestamp_ms is not None:
            self._last_motion_timestamp_ms = timestamp_ms
        return max(1.0 / 240.0, min(0.1, dt))

    def _apply_request(
        self,
        request: BodyMotionRequest,
        elapsed: float,
        positions: dict[str, BodyKinematicPoint],
        base_positions: dict[str, BodyKinematicPoint],
    ) -> None:
        if elapsed < request.timing.delay_seconds:
            return
        local = elapsed - request.timing.delay_seconds

        if request.operation is BodyMotionOperation.SEQUENCE:
            cursor = 0.0
            for child in request.children:
                duration = self._request_duration(child)
                if local < cursor:
                    return
                if local <= cursor + duration:
                    self._apply_request(child, local - cursor, positions, base_positions)
                    return
                if self._has_hold_final(child):
                    self._apply_request(child, duration, positions, base_positions)
                cursor += duration
            return

        if request.operation is BodyMotionOperation.PARALLEL:
            for child in request.children:
                self._apply_request(child, local, positions, base_positions)
            return

        if request.operation is BodyMotionOperation.REPEAT:
            child = request.children[0]
            child_duration = self._request_duration(child)
            if child_duration <= 0.0:
                return
            total = child_duration * request.timing.repetitions
            child_elapsed = child_duration if local >= total else local % child_duration
            self._apply_request(child, child_elapsed, positions, base_positions)
            return

        if request.operation in {
            BodyMotionOperation.HOLD,
            BodyMotionOperation.RELEASE,
        }:
            return

        duration = request.timing.duration_seconds
        progress = max(0.0, min(1.0, local / duration))
        if local > duration and not request.timing.hold_final:
            return
        self._apply_primitive(request, progress, positions, base_positions)

    def _apply_primitive(
        self,
        request: BodyMotionRequest,
        progress: float,
        positions: dict[str, BodyKinematicPoint],
        base_positions: dict[str, BodyKinematicPoint],
    ) -> None:
        target = request.target
        if target is None or target not in positions:
            return
        eased = self._easing(progress, request.timing.easing)
        strength = (
            eased
            if request.timing.hold_final
            else self._pulse(progress, request.timing.easing)
        )

        if request.operation is BodyMotionOperation.REACH:
            assert request.vector is not None
            destination = BodyKinematicPoint(
                request.vector.x,
                request.vector.y,
                request.vector.z,
            )
            positions[target] = base_positions[target].lerp(destination, strength)
            return

        if request.operation is BodyMotionOperation.TRANSLATE:
            assert request.vector is not None
            offset = BodyKinematicPoint(
                request.vector.x * strength,
                request.vector.y * strength,
                request.vector.z * strength,
            )
            self._translate_subtree(target, offset, positions)
            return

        if request.operation is BodyMotionOperation.OSCILLATE:
            assert request.vector is not None
            envelope = self._window(progress)
            phase = 2.0 * math.pi * request.timing.repetitions * progress
            amount = math.sin(phase) * envelope
            offset = BodyKinematicPoint(
                request.vector.x * amount,
                request.vector.y * amount,
                request.vector.z * amount,
            )
            self._translate_subtree(target, offset, positions)
            return

        pivot_id = request.pivot or self._motion_planner.default_pivot(target)
        if pivot_id is None or pivot_id not in positions:
            return

        if request.operation is BodyMotionOperation.ROTATE:
            angle = request.amount * request.direction * strength
            self._rotate_subtree(
                target,
                pivot_id,
                angle,
                request.axis,
                positions,
            )
            return

        if request.operation is BodyMotionOperation.CIRCLE:
            pivot = positions[pivot_id]
            start = base_positions[target]
            desired = self._circle_point(
                start,
                pivot,
                radius=request.radius,
                phase=(
                    2.0
                    * math.pi
                    * request.timing.repetitions
                    * progress
                    * request.direction
                ),
                axis=request.axis,
            )
            positions[target] = start.lerp(desired, self._window(progress))

    def _translate_subtree(
        self,
        target: str,
        offset: BodyKinematicPoint,
        positions: dict[str, BodyKinematicPoint],
    ) -> None:
        if target == "root":
            positions["root"] = positions["root"].translated(offset)
        for joint_id in self._DESCENDANTS.get(target, (target,)):
            if joint_id in positions:
                positions[joint_id] = positions[joint_id].translated(offset)

    def _rotate_subtree(
        self,
        target: str,
        pivot_id: str,
        angle: float,
        axis: str,
        positions: dict[str, BodyKinematicPoint],
    ) -> None:
        pivot = positions[pivot_id]
        for joint_id in self._DESCENDANTS.get(target, (target,)):
            point = positions.get(joint_id)
            if point is not None:
                positions[joint_id] = self._rotated_point(point, pivot, angle, axis)

    @staticmethod
    def _rotated_point(
        point: BodyKinematicPoint,
        pivot: BodyKinematicPoint,
        angle: float,
        axis: str,
    ) -> BodyKinematicPoint:
        cosine = math.cos(angle)
        sine = math.sin(angle)
        dx = point.x - pivot.x
        dy = point.y - pivot.y
        dz = point.z - pivot.z
        if axis == "x":
            return BodyKinematicPoint(
                point.x,
                pivot.y + dy * cosine - dz * sine,
                pivot.z + dy * sine + dz * cosine,
            )
        if axis == "y":
            return BodyKinematicPoint(
                pivot.x + dx * cosine + dz * sine,
                point.y,
                pivot.z - dx * sine + dz * cosine,
            )
        return BodyKinematicPoint(
            pivot.x + dx * cosine - dy * sine,
            pivot.y + dx * sine + dy * cosine,
            point.z,
        )

    @staticmethod
    def _circle_point(
        start: BodyKinematicPoint,
        pivot: BodyKinematicPoint,
        *,
        radius: float,
        phase: float,
        axis: str,
    ) -> BodyKinematicPoint:
        if axis == "x":
            start_angle = math.atan2(start.z - pivot.z, start.y - pivot.y)
            return BodyKinematicPoint(
                start.x,
                pivot.y + math.cos(start_angle + phase) * radius,
                pivot.z + math.sin(start_angle + phase) * radius,
            )
        if axis == "y":
            start_angle = math.atan2(start.z - pivot.z, start.x - pivot.x)
            return BodyKinematicPoint(
                pivot.x + math.cos(start_angle + phase) * radius,
                start.y,
                pivot.z + math.sin(start_angle + phase) * radius,
            )
        start_angle = math.atan2(start.y - pivot.y, start.x - pivot.x)
        return BodyKinematicPoint(
            pivot.x + math.cos(start_angle + phase) * radius,
            pivot.y + math.sin(start_angle + phase) * radius,
            start.z,
        )

    def _solve_limbs(
        self,
        positions: dict[str, BodyKinematicPoint],
        base_positions: dict[str, BodyKinematicPoint],
    ) -> None:
        for root_id, middle_id, end_id, bend_side in (
            ("left_shoulder", "left_elbow", "left_hand", -1),
            ("right_shoulder", "right_elbow", "right_hand", 1),
            ("left_hip", "left_knee", "left_ankle", -1),
            ("right_hip", "right_knee", "right_ankle", 1),
        ):
            if not all(key in positions for key in (root_id, middle_id, end_id)):
                continue
            upper = base_positions[root_id].distance_to(base_positions[middle_id])
            lower = base_positions[middle_id].distance_to(base_positions[end_id])
            positions[middle_id] = self._two_bone_middle(
                positions[root_id],
                positions[end_id],
                upper_length=upper,
                lower_length=lower,
                bend_side=bend_side,
            )

    @staticmethod
    def _two_bone_middle(
        root: BodyKinematicPoint,
        end: BodyKinematicPoint,
        *,
        upper_length: float,
        lower_length: float,
        bend_side: int,
    ) -> BodyKinematicPoint:
        dx = end.x - root.x
        dy = end.y - root.y
        distance = max(1e-6, math.hypot(dx, dy))
        maximum = max(1e-6, upper_length + lower_length - 1e-5)
        minimum = max(1e-6, abs(upper_length - lower_length) + 1e-5)
        clamped = max(minimum, min(maximum, distance))
        along = (
            upper_length * upper_length
            - lower_length * lower_length
            + clamped * clamped
        ) / (2.0 * clamped)
        height = math.sqrt(max(0.0, upper_length * upper_length - along * along))
        unit_x = dx / distance
        unit_y = dy / distance
        base_x = root.x + unit_x * along
        base_y = root.y + unit_y * along
        perpendicular_x = -unit_y * bend_side
        perpendicular_y = unit_x * bend_side
        return BodyKinematicPoint(
            base_x + perpendicular_x * height,
            base_y + perpendicular_y * height,
            root.z + (end.z - root.z) * min(1.0, along / clamped),
        )

    def _smooth_positions(
        self,
        positions: dict[str, BodyKinematicPoint],
        dt: float,
    ) -> dict[str, BodyKinematicPoint]:
        alpha = 1.0 - math.exp(-14.0 * dt)
        result: dict[str, BodyKinematicPoint] = {}
        for joint_id, target in positions.items():
            current = self._smoothed_positions.get(joint_id, target)
            next_point = current.lerp(target, alpha)
            self._smoothed_positions[joint_id] = next_point
            result[joint_id] = next_point
        return result

    def _capture_hold(self, target: str | None) -> None:
        if target is None:
            return
        if target == "root":
            self._held_positions[target] = self._latest_kinematic.root_position
            return
        joint = self._latest_kinematic.joint(target)
        if joint is not None:
            self._held_positions[target] = joint.position

    def _release_hold(self, target: str | None) -> None:
        if target is not None:
            self._held_positions.pop(target, None)

    def _capture_hold_final_targets(
        self,
        request: BodyMotionRequest,
        positions: dict[str, BodyKinematicPoint],
    ) -> None:
        if request.timing.hold_final and request.target in positions:
            assert request.target is not None
            self._held_positions[request.target] = positions[request.target]
        for child in request.children:
            self._capture_hold_final_targets(child, positions)

    @classmethod
    def _request_duration(cls, request: BodyMotionRequest) -> float:
        if request.operation in {
            BodyMotionOperation.HOLD,
            BodyMotionOperation.RELEASE,
        }:
            return 0.0
        if request.operation is BodyMotionOperation.SEQUENCE:
            return request.timing.delay_seconds + sum(
                cls._request_duration(child) for child in request.children
            )
        if request.operation is BodyMotionOperation.PARALLEL:
            return request.timing.delay_seconds + max(
                cls._request_duration(child) for child in request.children
            )
        if request.operation is BodyMotionOperation.REPEAT:
            return request.timing.delay_seconds + (
                cls._request_duration(request.children[0])
                * request.timing.repetitions
            )
        return request.timing.total_seconds

    @classmethod
    def _has_hold_final(cls, request: BodyMotionRequest) -> bool:
        return request.timing.hold_final or any(
            cls._has_hold_final(child) for child in request.children
        )

    @staticmethod
    def _easing(progress: float, easing: BodyMotionEasing) -> float:
        value = max(0.0, min(1.0, progress))
        if easing is BodyMotionEasing.LINEAR:
            return value
        if easing is BodyMotionEasing.EASE_IN_OUT:
            return 0.5 - 0.5 * math.cos(math.pi * value)
        return value * value * (3.0 - 2.0 * value)

    @classmethod
    def _pulse(cls, progress: float, easing: BodyMotionEasing) -> float:
        value = max(0.0, min(1.0, progress))
        if value < 0.24:
            return cls._easing(value / 0.24, easing)
        if value > 0.76:
            return cls._easing((1.0 - value) / 0.24, easing)
        return 1.0

    @staticmethod
    def _window(progress: float) -> float:
        value = max(0.0, min(1.0, progress))
        fade = min(1.0, value / 0.12, (1.0 - value) / 0.12)
        return max(0.0, fade * fade * (3.0 - 2.0 * fade))
