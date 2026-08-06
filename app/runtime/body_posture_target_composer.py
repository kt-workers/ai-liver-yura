from __future__ import annotations

from dataclasses import dataclass

from app.domain.body_activity_context import BodyPostureTendency
from app.domain.body_expression_input import BodyExpressionInput
from app.domain.body_motion_state import BodyInnerMotionState
from app.runtime.body_ambient_motion_generator import BodyAmbientMotionSample
from app.runtime.body_breathing_oscillator import BodyBreathingSample


@dataclass(frozen=True, slots=True)
class BodyPostureTarget:
    torso_pitch: float
    torso_roll: float
    body_height: float
    left_arm_raise: float
    right_arm_raise: float
    left_arm_in: float
    right_arm_in: float


class BodyPostureTargetComposer:
    """Activity姿勢・感情・対人的Overlayを胴体と腕の目標へ合成する。"""

    def compose(
        self,
        *,
        value: BodyExpressionInput,
        state: BodyInnerMotionState,
        ambient: BodyAmbientMotionSample,
        breathing: BodyBreathingSample,
    ) -> BodyPostureTarget:
        context = value.activity_context
        baseline = value.affect_baseline
        overlay = value.expression_overlay

        posture_pitch, posture_closedness, posture_height = self._posture_bias(
            context.posture_tendency
        )
        overlay_approach = overlay.approach if overlay is not None else 0.0
        overlay_openness = overlay.openness if overlay is not None else 0.5
        overlay_surprise = overlay.surprise if overlay is not None else 0.0
        overlay_assertiveness = overlay.assertiveness if overlay is not None else 0.0
        overlay_tension = overlay.tension if overlay is not None else 0.0
        overlay_warmth = overlay.warmth if overlay is not None else 0.5
        overlay_strength = overlay.intensity if overlay is not None else 0.0

        closedness = state.tension * 0.48 + state.avoidance * 0.42
        closedness += posture_closedness
        openness = state.confidence * 0.30 + state.engagement * 0.24
        openness += baseline.openness * 0.20
        openness += (overlay_openness - 0.5) * overlay_warmth * overlay_strength * 0.34
        arm_in = self._clamp(closedness - openness * 0.58, -1.0, 1.0)

        surprise = max(baseline.surprise, overlay_surprise * overlay_strength)
        arm_raise = self._clamp(
            state.arousal * 0.10
            + state.tension * 0.10
            + surprise * 0.22,
            0.0,
            0.42,
        )
        torso_pitch = self._clamp(
            posture_pitch
            - baseline.approach * 0.18
            - overlay_approach * overlay_strength * 0.24
            - state.engagement * 0.08
            + state.avoidance * 0.16
            + breathing.torso_pitch,
            -1.0,
            1.0,
        )
        torso_roll = self._clamp(
            ambient.posture_noise * (0.18 + state.movement_energy * 0.20)
            + state.tension * 0.025
            + overlay_tension * overlay_strength * 0.035,
            -1.0,
            1.0,
        )
        body_height = self._clamp(
            posture_height
            + breathing.body_height
            + surprise * 0.08
            + overlay_assertiveness * overlay_strength * 0.045
            - state.avoidance * 0.035,
            -1.0,
            1.0,
        )

        asymmetry = ambient.posture_noise * 0.10 * state.movement_energy
        return BodyPostureTarget(
            torso_pitch=torso_pitch,
            torso_roll=torso_roll,
            body_height=body_height,
            left_arm_raise=self._clamp(arm_raise + asymmetry, 0.0, 1.0),
            right_arm_raise=self._clamp(arm_raise - asymmetry, 0.0, 1.0),
            left_arm_in=self._clamp(arm_in + asymmetry, -1.0, 1.0),
            right_arm_in=self._clamp(arm_in - asymmetry, -1.0, 1.0),
        )

    @staticmethod
    def _posture_bias(
        posture: BodyPostureTendency,
    ) -> tuple[float, float, float]:
        if posture is BodyPostureTendency.OPEN:
            return -0.04, -0.20, 0.02
        if posture is BodyPostureTendency.CLOSED:
            return 0.08, 0.34, -0.025
        if posture is BodyPostureTendency.FORWARD:
            return -0.18, -0.04, 0.0
        if posture is BodyPostureTendency.WITHDRAWN:
            return 0.18, 0.22, -0.05
        return 0.0, 0.0, 0.0

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))
