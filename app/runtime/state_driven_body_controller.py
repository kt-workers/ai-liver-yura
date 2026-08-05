from __future__ import annotations

import math
from dataclasses import replace

from app.domain.body import BodyExpressionRequest
from app.domain.body_pose_frame import BodyBlendShape, BodyPoseFrame, BodyTrackingPose
from app.runtime.body_pose_3d_projector import (
    BodyPose3DProjector,
    KinematicProceduralBodyController,
)


def _clamp(value: float, minimum: float = -1.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, float(value)))


def _smoothstep(value: float) -> float:
    normalized = _clamp(value, 0.0, 1.0)
    return normalized * normalized * (3.0 - 2.0 * normalized)


class StateDrivenBodyController(KinematicProceduralBodyController):
    """内的状態・Activity・表情・発話を一つのBodyPoseFrameへ合成する。

    明示的な関節命令を主入力にせず、現在姿勢を維持するProcedural Controllerへ
    `BodyExpressionRequest`と発話状態を時間的なOverlayとして重ねる。表情、視線、
    頭、胴体、腕、呼吸、瞬き、口形は同じFrameに残る。
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._projector = BodyPose3DProjector()
        self._expression_request: BodyExpressionRequest | None = None
        self._expression_elapsed = 0.0
        self._expression_duration = 0.0
        self._speech_active = False
        self._speech_energy = 0.5
        self._speech_phase = 0.0

    @property
    def active_expression_id(self) -> str | None:
        request = self._expression_request
        return request.request_id if request is not None else None

    def apply_expression(self, request: BodyExpressionRequest) -> None:
        """人格的な高レベル表現を現在姿勢へ重ねる。"""

        self._expression_request = request
        self._expression_elapsed = 0.0
        self._expression_duration = (request.duration_hint_ms or 1800) / 1000.0

    def clear_expression(self) -> None:
        self._expression_request = None
        self._expression_elapsed = 0.0
        self._expression_duration = 0.0

    def set_speech_active(self, active: bool, *, energy: float = 0.5) -> None:
        self._speech_active = bool(active)
        self._speech_energy = _clamp(energy, 0.0, 1.0)
        if not self._speech_active:
            self._speech_phase = 0.0

    def tick(
        self,
        *,
        timestamp_ms: int | None = None,
        dt_seconds: float | None = None,
    ) -> BodyPoseFrame:
        dt = self._resolve_dt(dt_seconds)
        base_frame = super().tick(
            timestamp_ms=timestamp_ms,
            dt_seconds=dt_seconds,
        )
        pose, expression_shapes = self._compose_pose(base_frame.pose, dt)
        projected = self._projector.project(replace(base_frame, pose=pose))
        blend_shapes = self._merge_blend_shapes(
            projected.blend_shapes,
            expression_shapes,
        )
        self._advance(dt)
        return replace(projected, blend_shapes=blend_shapes)

    def _compose_pose(
        self,
        pose: BodyTrackingPose,
        dt: float,
    ) -> tuple[BodyTrackingPose, tuple[BodyBlendShape, ...]]:
        del dt
        request = self._expression_request
        envelope = self._expression_envelope()

        head_yaw = pose.head_yaw
        head_pitch = pose.head_pitch
        head_roll = pose.head_roll
        torso_pitch = pose.torso_pitch
        torso_roll = pose.torso_roll
        body_height = pose.body_height
        left_arm_raise = pose.left_arm_raise
        right_arm_raise = pose.right_arm_raise
        left_arm_in = pose.left_arm_in
        right_arm_in = pose.right_arm_in
        eye_left_open = pose.eye_left_open
        eye_right_open = pose.eye_right_open
        mouth_open = pose.mouth_open
        mouth_form = pose.mouth_form

        brow_raise = 0.0
        brow_lower = 0.0
        eye_squint = 0.0

        if request is not None and envelope > 0.0:
            expression = request.expression
            intensity = max(expression.intensity, request.facial_intensity * 0.65)
            strength = _clamp(intensity * envelope, 0.0, 1.0)
            phase = self._expression_elapsed / max(self._expression_duration, 0.001)

            # 意味軸から身体全体へ展開する。部位や固定モーション名は入力にしない。
            if expression.agreement >= 0.08:
                nod = math.sin(math.tau * phase * (1.4 + expression.arousal))
                head_pitch = _clamp(
                    head_pitch + nod * expression.agreement * strength * 0.24
                )
            elif expression.agreement <= -0.08:
                shake = math.sin(math.tau * phase * (1.8 + expression.arousal))
                head_yaw = _clamp(
                    head_yaw + shake * abs(expression.agreement) * strength * 0.34
                )
                head_roll = _clamp(head_roll - shake * strength * 0.06)

            torso_pitch = _clamp(
                torso_pitch - expression.approach * strength * 0.34
            )
            torso_roll = _clamp(
                torso_roll + expression.tension * strength * 0.035
            )

            openness_signal = (expression.openness - 0.5) * 2.0
            arm_shift = openness_signal * expression.warmth * strength * 0.34
            left_arm_in = _clamp(left_arm_in - arm_shift)
            right_arm_in = _clamp(right_arm_in - arm_shift)

            surprise = expression.surprise * strength
            left_arm_raise = _clamp(left_arm_raise + surprise * 0.22, 0.0, 1.0)
            right_arm_raise = _clamp(right_arm_raise + surprise * 0.22, 0.0, 1.0)
            body_height = _clamp(
                body_height + surprise * 0.08 + expression.assertiveness * strength * 0.045
            )

            facial = self._facial_targets(request)
            mouth_form = _clamp(
                mouth_form
                + facial["smile"] * strength
                - facial["frown"] * strength
            )
            mouth_open = _clamp(
                max(mouth_open, facial["jaw_open"] * strength),
                0.0,
                1.0,
            )
            eye_left_open = _clamp(
                eye_left_open
                + facial["eye_wide"] * strength * 0.28
                - facial["eye_squint"] * strength * 0.42,
                0.0,
                1.0,
            )
            eye_right_open = _clamp(
                eye_right_open
                + facial["eye_wide"] * strength * 0.28
                - facial["eye_squint"] * strength * 0.40,
                0.0,
                1.0,
            )
            brow_raise = facial["brow_raise"] * strength
            brow_lower = facial["brow_lower"] * strength
            eye_squint = facial["eye_squint"] * strength

        if self._speech_active:
            self._speech_phase += (
                math.tau * (3.1 + self._speech_energy * 2.4) / self.tick_hz
            )
            speech_open = (
                0.16
                + self._speech_energy * 0.30
                + (0.5 + 0.5 * math.sin(self._speech_phase))
                * (0.18 + self._speech_energy * 0.24)
            )
            mouth_open = _clamp(max(mouth_open, speech_open), 0.0, 1.0)

        composed = replace(
            pose,
            head_yaw=head_yaw,
            head_pitch=head_pitch,
            head_roll=head_roll,
            torso_pitch=torso_pitch,
            torso_roll=torso_roll,
            body_height=body_height,
            left_arm_raise=left_arm_raise,
            right_arm_raise=right_arm_raise,
            left_arm_in=left_arm_in,
            right_arm_in=right_arm_in,
            eye_left_open=eye_left_open,
            eye_right_open=eye_right_open,
            mouth_open=mouth_open,
            mouth_form=mouth_form,
        )
        shapes = (
            BodyBlendShape("brow_raise", _clamp(brow_raise, 0.0, 1.0)),
            BodyBlendShape("brow_lower", _clamp(brow_lower, 0.0, 1.0)),
            BodyBlendShape("eye_squint_left", _clamp(eye_squint, 0.0, 1.0)),
            BodyBlendShape("eye_squint_right", _clamp(eye_squint, 0.0, 1.0)),
        )
        return composed, shapes

    def _expression_envelope(self) -> float:
        if self._expression_request is None or self._expression_duration <= 0.0:
            return 0.0
        progress = _clamp(
            self._expression_elapsed / self._expression_duration,
            0.0,
            1.0,
        )
        if progress < 0.16:
            return _smoothstep(progress / 0.16)
        if progress > 0.82:
            return _smoothstep((1.0 - progress) / 0.18)
        return 1.0

    @staticmethod
    def _facial_targets(request: BodyExpressionRequest) -> dict[str, float]:
        expression = request.expression
        name = (request.facial_expression or expression.attitude).strip().lower()
        smile = max(0.0, expression.valence) * (0.55 + expression.warmth * 0.35)
        frown = max(0.0, -expression.valence) * (0.55 + expression.tension * 0.35)
        eye_wide = expression.surprise * 0.9
        eye_squint = expression.tension * max(0.0, -expression.valence) * 0.45
        jaw_open = expression.surprise * 0.72
        brow_raise = expression.surprise * 0.85
        brow_lower = expression.tension * max(0.0, -expression.valence) * 0.55

        if name in {"happy", "joy", "joyful", "amused", "smile", "cheerful"}:
            smile = max(smile, 0.88)
            eye_squint = max(eye_squint, 0.24)
        elif name in {"sad", "sadness", "frown", "lonely"}:
            frown = max(frown, 0.82)
            brow_raise = max(brow_raise, 0.32)
        elif name in {"angry", "anger", "annoyed", "irritated"}:
            frown = max(frown, 0.72)
            brow_lower = max(brow_lower, 0.88)
            eye_squint = max(eye_squint, 0.48)
        elif name in {"surprised", "surprise", "astonished"}:
            eye_wide = max(eye_wide, 0.92)
            jaw_open = max(jaw_open, 0.78)
            brow_raise = max(brow_raise, 0.92)
        elif name in {"fear", "afraid", "scared"}:
            eye_wide = max(eye_wide, 0.78)
            frown = max(frown, 0.48)
            brow_raise = max(brow_raise, 0.62)
        elif name in {"disgusted", "disgust", "uncomfortable"}:
            frown = max(frown, 0.72)
            eye_squint = max(eye_squint, 0.58)
            brow_lower = max(brow_lower, 0.52)
        elif name in {"curious", "interested", "thinking"}:
            smile = max(smile, 0.18)
            brow_raise = max(brow_raise, 0.42)

        return {
            "smile": _clamp(smile, 0.0, 1.0),
            "frown": _clamp(frown, 0.0, 1.0),
            "eye_wide": _clamp(eye_wide, 0.0, 1.0),
            "eye_squint": _clamp(eye_squint, 0.0, 1.0),
            "jaw_open": _clamp(jaw_open, 0.0, 1.0),
            "brow_raise": _clamp(brow_raise, 0.0, 1.0),
            "brow_lower": _clamp(brow_lower, 0.0, 1.0),
        }

    @staticmethod
    def _merge_blend_shapes(
        base: tuple[BodyBlendShape, ...],
        overlay: tuple[BodyBlendShape, ...],
    ) -> tuple[BodyBlendShape, ...]:
        values = {shape.name: shape.value for shape in base}
        values.update({shape.name: shape.value for shape in overlay})
        return tuple(
            BodyBlendShape(name, value)
            for name, value in sorted(values.items())
        )

    def _advance(self, dt: float) -> None:
        if self._expression_request is None:
            return
        self._expression_elapsed += dt
        if self._expression_elapsed >= self._expression_duration:
            self.clear_expression()

    def _resolve_dt(self, dt_seconds: float | None) -> float:
        if dt_seconds is None:
            return 1.0 / self.tick_hz
        if isinstance(dt_seconds, bool) or not isinstance(dt_seconds, (int, float)):
            raise TypeError("dt_seconds must be a number")
        return max(1.0 / 240.0, min(0.1, float(dt_seconds)))
