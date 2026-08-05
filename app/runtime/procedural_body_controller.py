from __future__ import annotations

import math
import random
from dataclasses import fields, replace
from time import monotonic

from app.domain.body_pose_frame import (
    BodyAttentionCandidate,
    BodyInnerMotionState,
    BodyPoseFrame,
    BodyTrackingPose,
    BodyTrackingVelocity,
)

_POSE_FIELDS = tuple(field.name for field in fields(BodyTrackingPose))
_UNIT_FIELDS = {
    "eye_left_open",
    "eye_right_open",
    "mouth_open",
    "left_arm_raise",
    "right_arm_raise",
}
_BODY_COMMAND_DEFAULT_DURATION_MS = {
    "right_hand_raise": 2400,
    "left_hand_raise": 2400,
    "both_hands_raise": 2400,
    "right_hand_wave": 2800,
    "left_hand_wave": 2800,
    "both_hands_wave": 2800,
    "eyes_close": 2200,
    "eyes_open": 1600,
    "blink": 650,
    "mouth_open": 2200,
    "mouth_close": 1600,
    "head_circle": 2600,
    "bow": 2300,
    "jump": 1800,
    "body_sway": 3000,
    "body_twist": 2800,
}


class ProceduralBodyController:
    """内的状態と注意候補から連続トラッキング姿勢を生成する。

    完成済み待機モーションを順番に再生せず、現在姿勢・速度・相関揺らぎを
    保持しながら毎Tickの目標姿勢を更新する。明示的な身体操作も現在姿勢へ
    一時的な目標・軌道として重ね、ホーム姿勢へ瞬間移動しない。
    """

    def __init__(
        self,
        *,
        tick_hz: float = 30.0,
        seed: int | None = None,
        inner_state: BodyInnerMotionState | None = None,
    ) -> None:
        if isinstance(tick_hz, bool) or not isinstance(tick_hz, (int, float)):
            raise TypeError("tick_hz must be a number")
        if not 10.0 <= float(tick_hz) <= 120.0:
            raise ValueError("tick_hz must be between 10 and 120")
        self._tick_hz = float(tick_hz)
        self._random = random.Random(seed)
        self._inner_state = inner_state or BodyInnerMotionState()
        neutral = BodyTrackingPose()
        self._current = {name: getattr(neutral, name) for name in _POSE_FIELDS}
        self._velocity = {name: 0.0 for name in _POSE_FIELDS}
        self._candidates: tuple[BodyAttentionCandidate, ...] = ()
        self._selected_candidate: BodyAttentionCandidate | None = None
        self._attention_elapsed = 0.0
        self._attention_dwell_target = 1.5
        self._scan_x = 0.0
        self._scan_y = 0.0
        self._scan_vx = 0.0
        self._scan_vy = 0.0
        self._posture_noise = 0.0
        self._posture_noise_velocity = 0.0
        self._head_noise = 0.0
        self._head_noise_velocity = 0.0
        self._breathing_phase = 0.0
        self._blink_elapsed = 0.0
        self._blink_progress: float | None = None
        self._body_command: str | None = None
        self._body_command_elapsed = 0.0
        self._body_command_duration = 0.0
        self._sequence = 0
        self._last_timestamp_ms: int | None = None

    @property
    def tick_hz(self) -> float:
        return self._tick_hz

    @property
    def inner_state(self) -> BodyInnerMotionState:
        return self._inner_state

    @property
    def active_body_command(self) -> str | None:
        return self._body_command

    def set_inner_state(self, state: BodyInnerMotionState) -> None:
        self._inner_state = state

    def update_inner_state(self, **changes: float) -> None:
        unknown = set(changes) - {field.name for field in fields(BodyInnerMotionState)}
        if unknown:
            raise ValueError(f"unknown inner state fields: {sorted(unknown)}")
        self._inner_state = replace(self._inner_state, **changes)

    def set_attention_candidates(
        self,
        candidates: tuple[BodyAttentionCandidate, ...] | list[BodyAttentionCandidate],
    ) -> None:
        normalized = tuple(candidates)
        if len(normalized) > 32:
            raise ValueError("at most 32 attention candidates are supported")
        if self._selected_candidate is not None and not any(
            candidate.candidate_id == self._selected_candidate.candidate_id
            for candidate in normalized
        ):
            self._selected_candidate = None
            self._attention_elapsed = 0.0
        self._candidates = normalized

    def apply_body_command(
        self,
        command: str,
        *,
        duration_ms: int | None = None,
    ) -> None:
        normalized = command.strip().lower()
        if normalized not in _BODY_COMMAND_DEFAULT_DURATION_MS:
            raise ValueError(f"unsupported body command: {command}")
        resolved_duration = (
            _BODY_COMMAND_DEFAULT_DURATION_MS[normalized]
            if duration_ms is None
            else duration_ms
        )
        if isinstance(resolved_duration, bool) or not isinstance(resolved_duration, int):
            raise TypeError("duration_ms must be an integer")
        if not 200 <= resolved_duration <= 10_000:
            raise ValueError("duration_ms must be between 200 and 10000")
        self._body_command = normalized
        self._body_command_elapsed = 0.0
        self._body_command_duration = resolved_duration / 1000.0

    def clear_body_command(self) -> None:
        self._body_command = None
        self._body_command_elapsed = 0.0
        self._body_command_duration = 0.0

    def tick(
        self,
        *,
        timestamp_ms: int | None = None,
        dt_seconds: float | None = None,
    ) -> BodyPoseFrame:
        now_ms = int(monotonic() * 1000) if timestamp_ms is None else timestamp_ms
        if dt_seconds is None:
            if self._last_timestamp_ms is None:
                dt = 1.0 / self._tick_hz
            else:
                dt = max(1.0 / 240.0, min(0.1, (now_ms - self._last_timestamp_ms) / 1000.0))
        else:
            if isinstance(dt_seconds, bool) or not isinstance(dt_seconds, (int, float)):
                raise TypeError("dt_seconds must be a number")
            dt = max(1.0 / 240.0, min(0.1, float(dt_seconds)))
        self._last_timestamp_ms = now_ms

        self._update_attention(dt)
        self._update_correlated_noise(dt)
        self._update_blink(dt)
        target = self._target_pose(dt)
        self._apply_body_command_target(target)
        self._integrate_pose(target, dt)
        self._advance_body_command(dt)
        self._sequence += 1

        return BodyPoseFrame(
            sequence=self._sequence,
            timestamp_ms=now_ms,
            pose=BodyTrackingPose(**self._current),
            velocity=BodyTrackingVelocity(**self._velocity),
            inner_state=self._inner_state,
            attention_target_id=(
                self._selected_candidate.candidate_id
                if self._selected_candidate is not None
                else "ambient_scan"
            ),
            attention_dwell_ms=round(self._attention_elapsed * 1000),
        )

    def _update_attention(self, dt: float) -> None:
        self._attention_elapsed += dt
        state = self._inner_state
        selected_missing = self._selected_candidate is not None and not any(
            candidate.candidate_id == self._selected_candidate.candidate_id
            for candidate in self._candidates
        )
        reconsider_rate = 0.10 + state.curiosity * 0.34 + state.tension * 0.18
        should_reconsider = (
            self._selected_candidate is None
            or selected_missing
            or self._attention_elapsed >= self._attention_dwell_target
            or (
                self._attention_elapsed >= 0.45
                and self._random.random() < reconsider_rate * dt
            )
        )
        if not should_reconsider:
            return

        candidate = self._choose_attention_candidate()
        if candidate is not None:
            changed = (
                self._selected_candidate is None
                or candidate.candidate_id != self._selected_candidate.candidate_id
            )
            self._selected_candidate = candidate
            if changed:
                self._attention_elapsed = 0.0
            base_dwell = 0.65 + candidate.stability * 2.3 + state.engagement * candidate.relevance * 1.7
            base_dwell -= state.curiosity * candidate.novelty * 0.7
            base_dwell -= state.tension * candidate.threat * 0.45
            self._attention_dwell_target = max(
                0.45,
                min(4.8, base_dwell * self._random.uniform(0.78, 1.28)),
            )
        elif self._selected_candidate is not None:
            self._selected_candidate = None
            self._attention_elapsed = 0.0
            self._attention_dwell_target = self._random.uniform(0.8, 2.5)

    def _choose_attention_candidate(self) -> BodyAttentionCandidate | None:
        if not self._candidates:
            return None
        state = self._inner_state
        weighted: list[tuple[BodyAttentionCandidate, float]] = []
        for candidate in self._candidates:
            score = 0.12
            score += candidate.salience * 0.72
            score += candidate.novelty * state.curiosity * 0.82
            score += candidate.threat * state.tension * 0.95
            score += candidate.relevance * state.engagement * 0.88
            if self._selected_candidate is not None and candidate.candidate_id == self._selected_candidate.candidate_id:
                score += candidate.stability * 0.55
            score *= 1.0 - state.avoidance * candidate.relevance * 0.38
            weighted.append((candidate, max(0.01, score)))
        total = sum(weight for _, weight in weighted)
        cursor = self._random.random() * total
        for candidate, weight in weighted:
            cursor -= weight
            if cursor <= 0.0:
                return candidate
        return weighted[-1][0]

    def _update_correlated_noise(self, dt: float) -> None:
        state = self._inner_state
        scan_sigma = 0.08 + state.curiosity * 0.34 + state.tension * 0.16
        scan_reversion = 0.65 + state.engagement * 0.55
        self._scan_vx += (-scan_reversion * self._scan_x - 1.7 * self._scan_vx) * dt
        self._scan_vy += (-scan_reversion * self._scan_y - 1.8 * self._scan_vy) * dt
        self._scan_vx += self._random.gauss(0.0, scan_sigma) * math.sqrt(dt)
        self._scan_vy += self._random.gauss(0.0, scan_sigma * 0.72) * math.sqrt(dt)
        self._scan_x = max(-0.82, min(0.82, self._scan_x + self._scan_vx * dt))
        self._scan_y = max(-0.58, min(0.58, self._scan_y + self._scan_vy * dt))

        posture_sigma = 0.025 + state.movement_energy * 0.08
        self._posture_noise_velocity += (
            -0.42 * self._posture_noise - 0.95 * self._posture_noise_velocity
        ) * dt
        self._posture_noise_velocity += self._random.gauss(0.0, posture_sigma) * math.sqrt(dt)
        self._posture_noise = max(
            -0.24,
            min(0.24, self._posture_noise + self._posture_noise_velocity * dt),
        )

        head_sigma = 0.02 + state.arousal * 0.055 + state.curiosity * 0.035
        self._head_noise_velocity += (
            -0.58 * self._head_noise - 1.1 * self._head_noise_velocity
        ) * dt
        self._head_noise_velocity += self._random.gauss(0.0, head_sigma) * math.sqrt(dt)
        self._head_noise = max(-0.18, min(0.18, self._head_noise + self._head_noise_velocity * dt))

    def _update_blink(self, dt: float) -> None:
        self._blink_elapsed += dt
        state = self._inner_state
        if self._blink_progress is None:
            minimum_interval = 1.25 + (1.0 - state.tension) * 0.75
            hazard = 0.10 + state.tension * 0.21 + state.arousal * 0.11
            if self._blink_elapsed >= minimum_interval and self._random.random() < hazard * dt:
                self._blink_progress = 0.0
                self._blink_elapsed = 0.0
            return
        self._blink_progress += dt / max(0.16, 0.24 - state.tension * 0.055)
        if self._blink_progress >= 1.0:
            self._blink_progress = None

    def _target_pose(self, dt: float) -> dict[str, float]:
        del dt
        state = self._inner_state
        self._breathing_phase += (
            2.0
            * math.pi
            * (0.13 + state.arousal * 0.09 + state.tension * 0.055)
            / self._tick_hz
        )
        breath = math.sin(self._breathing_phase)
        breath_amplitude = 0.025 + state.movement_energy * 0.035 + state.arousal * 0.018

        if self._selected_candidate is None:
            target_x = self._scan_x
            target_y = self._scan_y
            target_strength = 0.28 + state.curiosity * 0.52 + state.tension * 0.22
        else:
            target_x = self._selected_candidate.x
            target_y = self._selected_candidate.y
            target_strength = 0.55 + self._selected_candidate.salience * 0.35
        target_x *= target_strength
        target_y *= target_strength

        gaze_x = max(-1.0, min(1.0, target_x + self._head_noise * 0.12))
        gaze_y = max(-1.0, min(1.0, target_y + self._head_noise * 0.08))
        gaze_distance = min(1.0, math.hypot(gaze_x, gaze_y))
        head_follow = 0.28 + gaze_distance * 0.48 + state.engagement * 0.12
        torso_follow = max(0.0, gaze_distance - 0.34) * (0.18 + state.confidence * 0.20)

        closedness = state.tension * 0.62 + state.avoidance * 0.45
        openness = state.confidence * 0.42 + state.engagement * 0.32
        arm_in = max(-0.35, min(0.72, closedness - openness * 0.55))
        arm_raise = max(0.0, min(0.28, state.arousal * 0.12 + state.tension * 0.14))
        forward = state.engagement * 0.24 + state.curiosity * 0.16 - state.avoidance * 0.28
        stiffness = state.tension * 0.18

        blink_closure = 0.0
        if self._blink_progress is not None:
            blink_closure = math.sin(math.pi * min(1.0, self._blink_progress))

        return {
            "head_yaw": max(-1.0, min(1.0, gaze_x * head_follow)),
            "head_pitch": max(-1.0, min(1.0, gaze_y * head_follow + self._head_noise * 0.16)),
            "head_roll": max(-1.0, min(1.0, -gaze_x * 0.08 + self._head_noise * 0.25)),
            "gaze_x": gaze_x,
            "gaze_y": gaze_y,
            "eye_left_open": max(0.0, min(1.0, 1.0 - blink_closure)),
            "eye_right_open": max(0.0, min(1.0, 1.0 - blink_closure * 0.97)),
            "mouth_open": 0.0,
            "mouth_form": max(-1.0, min(1.0, state.confidence * 0.14 - state.tension * 0.12)),
            "torso_yaw": max(-1.0, min(1.0, gaze_x * torso_follow)),
            "torso_pitch": max(-1.0, min(1.0, -forward + breath * 0.025)),
            "torso_roll": max(-1.0, min(1.0, self._posture_noise - gaze_x * 0.035)),
            "body_height": max(-1.0, min(1.0, breath * breath_amplitude - stiffness * 0.025)),
            "left_arm_raise": arm_raise,
            "right_arm_raise": max(0.0, min(1.0, arm_raise * 0.92)),
            "left_arm_in": max(-1.0, min(1.0, arm_in + self._posture_noise * 0.12)),
            "right_arm_in": max(-1.0, min(1.0, arm_in - self._posture_noise * 0.12)),
        }

    def _apply_body_command_target(self, target: dict[str, float]) -> None:
        command = self._body_command
        if command is None or self._body_command_duration <= 0.0:
            return
        progress = max(
            0.0,
            min(1.0, self._body_command_elapsed / self._body_command_duration),
        )
        envelope = self._command_envelope(progress)
        phase = progress * math.tau

        if command in {"right_hand_raise", "right_hand_wave", "both_hands_raise", "both_hands_wave"}:
            target["right_arm_raise"] = max(target["right_arm_raise"], 0.96 * envelope)
            target["right_arm_in"] = min(target["right_arm_in"], -0.16 * envelope)
        if command in {"left_hand_raise", "left_hand_wave", "both_hands_raise", "both_hands_wave"}:
            target["left_arm_raise"] = max(target["left_arm_raise"], 0.96 * envelope)
            target["left_arm_in"] = min(target["left_arm_in"], -0.16 * envelope)
        if command in {"right_hand_wave", "both_hands_wave"}:
            target["right_arm_in"] += math.sin(phase * 3.0) * 0.42 * envelope
        if command in {"left_hand_wave", "both_hands_wave"}:
            target["left_arm_in"] -= math.sin(phase * 3.0) * 0.42 * envelope

        if command == "eyes_close":
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
            target["head_yaw"] = max(-1.0, min(1.0, target["head_yaw"] + math.sin(phase) * 0.68 * envelope))
            target["head_pitch"] = max(-1.0, min(1.0, target["head_pitch"] - math.cos(phase) * 0.48 * envelope))
            target["head_roll"] = max(-1.0, min(1.0, target["head_roll"] + math.sin(phase) * 0.24 * envelope))
        elif command == "bow":
            target["torso_pitch"] = min(target["torso_pitch"], -0.82 * envelope)
            target["head_pitch"] = min(target["head_pitch"], -0.48 * envelope)
            target["body_height"] = min(target["body_height"], -0.12 * envelope)
        elif command == "jump":
            target["body_height"] = max(target["body_height"], math.sin(math.pi * progress) * 0.88)
            target["left_arm_raise"] = max(target["left_arm_raise"], envelope * 0.38)
            target["right_arm_raise"] = max(target["right_arm_raise"], envelope * 0.38)
        elif command == "body_sway":
            target["torso_roll"] = max(-1.0, min(1.0, target["torso_roll"] + math.sin(phase * 2.0) * 0.52 * envelope))
        elif command == "body_twist":
            target["torso_yaw"] = max(-1.0, min(1.0, target["torso_yaw"] + math.sin(phase * 2.0) * 0.64 * envelope))

    def _advance_body_command(self, dt: float) -> None:
        if self._body_command is None:
            return
        self._body_command_elapsed += dt
        if self._body_command_elapsed >= self._body_command_duration:
            self.clear_body_command()

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

    def _integrate_pose(self, target: dict[str, float], dt: float) -> None:
        for name in _POSE_FIELDS:
            stiffness = self._axis_stiffness(name)
            damping = 2.0 * math.sqrt(stiffness) * 0.86
            acceleration = stiffness * (target[name] - self._current[name]) - damping * self._velocity[name]
            self._velocity[name] = max(-8.0, min(8.0, self._velocity[name] + acceleration * dt))
            self._current[name] += self._velocity[name] * dt
            minimum, maximum = ((0.0, 1.0) if name in _UNIT_FIELDS else (-1.0, 1.0))
            if self._current[name] < minimum:
                self._current[name] = minimum
                self._velocity[name] = max(0.0, self._velocity[name])
            elif self._current[name] > maximum:
                self._current[name] = maximum
                self._velocity[name] = min(0.0, self._velocity[name])

    @staticmethod
    def _axis_stiffness(name: str) -> float:
        if name in {"gaze_x", "gaze_y", "eye_left_open", "eye_right_open"}:
            return 42.0
        if name.startswith("head_"):
            return 13.0
        if name.startswith("torso_") or name == "body_height":
            return 5.2
        if name.startswith("left_arm") or name.startswith("right_arm"):
            return 4.4
        if name.startswith("mouth_"):
            return 22.0
        return 8.0
