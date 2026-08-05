from __future__ import annotations

import math
from dataclasses import dataclass, fields, replace

from app.domain.body_pose_frame import (
    BodyAttentionCandidate,
    BodyInnerMotionState,
    BodyJointPose,
    BodyPoseFrame,
    BodyQuaternion,
    BodyTrackingPose,
    BodyTrackingVelocity,
)
from app.runtime.body_pose_3d_projector import BodyPose3DProjector
from app.runtime.procedural_body_controller import ProceduralBodyController


_COMMAND_DEFAULT_DURATION_MS: dict[str, int] = {
    "right_hand_raise": 1800,
    "left_hand_raise": 1800,
    "both_hands_raise": 1800,
    "right_hand_lower": 1400,
    "left_hand_lower": 1400,
    "both_hands_lower": 1400,
    "right_hand_wave": 2800,
    "left_hand_wave": 2800,
    "both_hands_wave": 2800,
    "right_leg_raise": 2200,
    "left_leg_raise": 2200,
    "eyes_close": 1600,
    "eyes_open": 1200,
    "blink": 650,
    "mouth_open": 1600,
    "mouth_close": 1200,
    "head_circle": 2600,
    "bow": 2300,
    "jump": 1800,
    "body_sway": 3000,
    "body_twist": 2800,
}
SUPPORTED_CORE_BODY_COMMANDS = frozenset(_COMMAND_DEFAULT_DURATION_MS)

_COMMAND_CHANNELS: dict[str, frozenset[str]] = {
    "right_hand_raise": frozenset({"right_arm"}),
    "right_hand_lower": frozenset({"right_arm"}),
    "right_hand_wave": frozenset({"right_arm"}),
    "left_hand_raise": frozenset({"left_arm"}),
    "left_hand_lower": frozenset({"left_arm"}),
    "left_hand_wave": frozenset({"left_arm"}),
    "both_hands_raise": frozenset({"left_arm", "right_arm"}),
    "both_hands_lower": frozenset({"left_arm", "right_arm"}),
    "both_hands_wave": frozenset({"left_arm", "right_arm"}),
    "right_leg_raise": frozenset({"right_leg", "balance"}),
    "left_leg_raise": frozenset({"left_leg", "balance"}),
    "eyes_close": frozenset({"eyes"}),
    "eyes_open": frozenset({"eyes"}),
    "blink": frozenset({"eyes"}),
    "mouth_open": frozenset({"mouth"}),
    "mouth_close": frozenset({"mouth"}),
    "head_circle": frozenset({"head"}),
    "bow": frozenset({"torso", "head"}),
    "jump": frozenset({"root", "balance"}),
    "body_sway": frozenset({"torso"}),
    "body_twist": frozenset({"torso"}),
}


def body_command_channels(command: str) -> frozenset[str]:
    return _COMMAND_CHANNELS.get(command.strip().lower(), frozenset({"unknown"}))


def group_body_actions(actions: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    """同時実行可能な部位命令をまとめ、同一部位の反復を逐次Stepへ分ける。"""

    groups: list[tuple[str, ...]] = []
    current: list[str] = []
    occupied: set[str] = set()
    for raw_action in actions:
        action = raw_action.strip().lower()
        channels = set(body_command_channels(action))
        if current and occupied.intersection(channels):
            groups.append(tuple(current))
            current = []
            occupied = set()
        current.append(action)
        occupied.update(channels)
    if current:
        groups.append(tuple(current))
    return tuple(groups)


@dataclass(slots=True)
class _CommandTrack:
    command: str
    elapsed: float
    duration: float

    @property
    def progress(self) -> float:
        if self.duration <= 0.0:
            return 1.0
        return max(0.0, min(1.0, self.elapsed / self.duration))


class CoreCommandBodyController:
    """Core身体命令を環境由来の連続姿勢へ重ねるController。

    ベースのProceduralBodyControllerは心境・注意・呼吸・瞬きを生成する。この層は
    明示命令を部位別Trackとして重ねるため、左腕と右脚など独立部位を同時に動かせる。
    同一部位の反復はCoreBodyPoseRuntimeが逐次Stepとして投入する。
    """

    def __init__(
        self,
        *,
        tick_hz: float = 30.0,
        seed: int | None = None,
        inner_state: BodyInnerMotionState | None = None,
    ) -> None:
        self._base = ProceduralBodyController(
            tick_hz=tick_hz,
            seed=seed,
            inner_state=inner_state,
        )
        self._projector = BodyPose3DProjector()
        self._tracks: list[_CommandTrack] = []
        self._last_pose: BodyTrackingPose | None = None

    @property
    def tick_hz(self) -> float:
        return self._base.tick_hz

    @property
    def inner_state(self) -> BodyInnerMotionState:
        return self._base.inner_state

    @property
    def active_body_command(self) -> str | None:
        return self._tracks[0].command if self._tracks else None

    @property
    def active_body_commands(self) -> tuple[str, ...]:
        return tuple(track.command for track in self._tracks)

    def set_inner_state(self, state: BodyInnerMotionState) -> None:
        self._base.set_inner_state(state)

    def update_inner_state(self, **changes: float) -> None:
        self._base.update_inner_state(**changes)

    def set_attention_candidates(
        self,
        candidates: tuple[BodyAttentionCandidate, ...] | list[BodyAttentionCandidate],
    ) -> None:
        self._base.set_attention_candidates(candidates)

    def apply_body_command(
        self,
        command: str,
        *,
        duration_ms: int | None = None,
    ) -> None:
        self.apply_body_commands((command,), duration_ms=duration_ms)

    def apply_body_commands(
        self,
        commands: tuple[str, ...] | list[str],
        *,
        duration_ms: int | None = None,
    ) -> None:
        normalized: list[str] = []
        occupied: set[str] = set()
        for raw_command in commands:
            command = raw_command.strip().lower()
            if command not in SUPPORTED_CORE_BODY_COMMANDS:
                raise ValueError(f"unsupported body command: {raw_command}")
            channels = set(body_command_channels(command))
            if occupied.intersection(channels):
                raise ValueError("conflicting body commands must be submitted sequentially")
            normalized.append(command)
            occupied.update(channels)
        if not normalized:
            return

        tracks: list[_CommandTrack] = []
        for command in normalized:
            resolved_ms = (
                _COMMAND_DEFAULT_DURATION_MS[command]
                if duration_ms is None
                else duration_ms
            )
            if isinstance(resolved_ms, bool) or not isinstance(resolved_ms, int):
                raise TypeError("duration_ms must be an integer")
            if not 200 <= resolved_ms <= 10_000:
                raise ValueError("duration_ms must be between 200 and 10000")
            tracks.append(
                _CommandTrack(
                    command=command,
                    elapsed=0.0,
                    duration=resolved_ms / 1000.0,
                )
            )
        self._tracks = tracks

    def clear_body_command(self) -> None:
        self._tracks.clear()

    def tick(
        self,
        *,
        timestamp_ms: int | None = None,
        dt_seconds: float | None = None,
    ) -> BodyPoseFrame:
        dt = 1.0 / self.tick_hz if dt_seconds is None else float(dt_seconds)
        dt = max(1.0 / 240.0, min(0.1, dt))
        base_frame = self._base.tick(
            timestamp_ms=timestamp_ms,
            dt_seconds=dt,
        )
        pose_values = {
            value_field.name: getattr(base_frame.pose, value_field.name)
            for value_field in fields(BodyTrackingPose)
        }
        leg_raise = {"left": 0.0, "right": 0.0}
        for track in self._tracks:
            self._apply_track(pose_values, leg_raise, track)

        pose = BodyTrackingPose(**pose_values)
        velocity = self._velocity_from_pose(pose, base_frame.velocity, dt)
        self._last_pose = pose
        projected = self._projector.project(
            replace(
                base_frame,
                pose=pose,
                velocity=velocity,
                joints=(),
                blend_shapes=(),
            )
        )
        projected = self._with_leg_joints(projected, leg_raise)
        self._advance_tracks(dt)
        return projected

    def _apply_track(
        self,
        target: dict[str, float],
        leg_raise: dict[str, float],
        track: _CommandTrack,
    ) -> None:
        command = track.command
        progress = track.progress
        envelope = self._command_envelope(progress)
        phase = progress * math.tau

        if command in {
            "right_hand_raise",
            "right_hand_wave",
            "both_hands_raise",
            "both_hands_wave",
        }:
            target["right_arm_raise"] = max(target["right_arm_raise"], 0.98 * envelope)
            target["right_arm_in"] = min(target["right_arm_in"], -0.16 * envelope)
        if command in {
            "left_hand_raise",
            "left_hand_wave",
            "both_hands_raise",
            "both_hands_wave",
        }:
            target["left_arm_raise"] = max(target["left_arm_raise"], 0.98 * envelope)
            target["left_arm_in"] = min(target["left_arm_in"], -0.16 * envelope)
        if command in {"right_hand_lower", "both_hands_lower"}:
            target["right_arm_raise"] *= 1.0 - envelope
            target["right_arm_in"] *= 1.0 - envelope
        if command in {"left_hand_lower", "both_hands_lower"}:
            target["left_arm_raise"] *= 1.0 - envelope
            target["left_arm_in"] *= 1.0 - envelope
        if command in {"right_hand_wave", "both_hands_wave"}:
            target["right_arm_in"] += math.sin(phase * 3.0) * 0.42 * envelope
        if command in {"left_hand_wave", "both_hands_wave"}:
            target["left_arm_in"] -= math.sin(phase * 3.0) * 0.42 * envelope

        if command == "right_leg_raise":
            leg_raise["right"] = max(leg_raise["right"], 0.96 * envelope)
            target["torso_roll"] -= 0.13 * envelope
            target["body_height"] -= 0.04 * envelope
        elif command == "left_leg_raise":
            leg_raise["left"] = max(leg_raise["left"], 0.96 * envelope)
            target["torso_roll"] += 0.13 * envelope
            target["body_height"] -= 0.04 * envelope
        elif command == "eyes_close":
            target["eye_left_open"] = min(target["eye_left_open"], 1.0 - envelope)
            target["eye_right_open"] = min(target["eye_right_open"], 1.0 - envelope)
        elif command == "eyes_open":
            target["eye_left_open"] = max(target["eye_left_open"], envelope)
            target["eye_right_open"] = max(target["eye_right_open"], envelope)
        elif command == "blink":
            closure = math.sin(math.pi * progress)
            target["eye_left_open"] = min(target["eye_left_open"], 1.0 - closure)
            target["eye_right_open"] = min(target["eye_right_open"], 1.0 - closure)
        elif command == "mouth_open":
            target["mouth_open"] = max(target["mouth_open"], 0.92 * envelope)
        elif command == "mouth_close":
            target["mouth_open"] = min(target["mouth_open"], 1.0 - envelope)
        elif command == "head_circle":
            target["head_yaw"] = self._clamp_axis(target["head_yaw"] + math.sin(phase) * 0.68 * envelope)
            target["head_pitch"] = self._clamp_axis(target["head_pitch"] - math.cos(phase) * 0.48 * envelope)
            target["head_roll"] = self._clamp_axis(target["head_roll"] + math.sin(phase) * 0.24 * envelope)
        elif command == "bow":
            target["torso_pitch"] = min(target["torso_pitch"], -0.82 * envelope)
            target["head_pitch"] = min(target["head_pitch"], -0.48 * envelope)
            target["body_height"] = min(target["body_height"], -0.12 * envelope)
        elif command == "jump":
            target["body_height"] = max(target["body_height"], math.sin(math.pi * progress) * 0.88)
            target["left_arm_raise"] = max(target["left_arm_raise"], envelope * 0.38)
            target["right_arm_raise"] = max(target["right_arm_raise"], envelope * 0.38)
        elif command == "body_sway":
            target["torso_roll"] = self._clamp_axis(
                target["torso_roll"] + math.sin(phase * 2.0) * 0.52 * envelope
            )
        elif command == "body_twist":
            target["torso_yaw"] = self._clamp_axis(
                target["torso_yaw"] + math.sin(phase * 2.0) * 0.64 * envelope
            )

    def _velocity_from_pose(
        self,
        pose: BodyTrackingPose,
        fallback: BodyTrackingVelocity,
        dt: float,
    ) -> BodyTrackingVelocity:
        if self._last_pose is None:
            return fallback
        values: dict[str, float] = {}
        for value_field in fields(BodyTrackingPose):
            name = value_field.name
            value = (getattr(pose, name) - getattr(self._last_pose, name)) / dt
            values[name] = max(-8.0, min(8.0, value))
        return BodyTrackingVelocity(**values)

    @staticmethod
    def _with_leg_joints(
        frame: BodyPoseFrame,
        leg_raise: dict[str, float],
    ) -> BodyPoseFrame:
        joints = [
            joint
            for joint in frame.joints
            if joint.joint_id
            not in {
                "left_upper_leg",
                "left_lower_leg",
                "right_upper_leg",
                "right_lower_leg",
            }
        ]
        for side in ("left", "right"):
            raise_amount = leg_raise[side]
            lateral = (-1.0 if side == "left" else 1.0) * raise_amount
            joints.extend(
                (
                    BodyJointPose(
                        f"{side}_upper_leg",
                        BodyQuaternion.from_euler_radians(
                            x=-raise_amount * math.radians(76.0),
                            z=lateral * math.radians(9.0),
                        ),
                    ),
                    BodyJointPose(
                        f"{side}_lower_leg",
                        BodyQuaternion.from_euler_radians(
                            x=raise_amount * math.radians(42.0),
                        ),
                    ),
                )
            )
        return replace(frame, joints=tuple(joints))

    def _advance_tracks(self, dt: float) -> None:
        remaining: list[_CommandTrack] = []
        for track in self._tracks:
            track.elapsed += dt
            if track.elapsed < track.duration:
                remaining.append(track)
        self._tracks = remaining

    @staticmethod
    def _command_envelope(progress: float) -> float:
        if progress <= 0.18:
            normalized = progress / 0.18
            return normalized * normalized * (3.0 - 2.0 * normalized)
        if progress >= 0.82:
            normalized = (1.0 - progress) / 0.18
            normalized = max(0.0, min(1.0, normalized))
            return normalized * normalized * (3.0 - 2.0 * normalized)
        return 1.0

    @staticmethod
    def _clamp_axis(value: float) -> float:
        return max(-1.0, min(1.0, value))
