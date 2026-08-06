from __future__ import annotations

import math
from dataclasses import dataclass

from app.domain.body_attention_intent import BodyAttentionBehavior, BodyAttentionIntent
from app.domain.body_motion_state import BodyInnerMotionState
from app.runtime.body_ambient_motion_generator import BodyAmbientMotionSample
from app.runtime.body_attention_selector import BodyAttentionSelection
from app.runtime.body_expression_gesture_generator import (
    BodyExpressionGestureSample,
)


@dataclass(frozen=True, slots=True)
class BodyGazeTarget:
    gaze_x: float
    gaze_y: float
    head_yaw: float
    head_pitch: float
    head_roll: float
    torso_yaw: float


class BodyGazeTargetComposer:
    """注意選択・微動・対人的頭部Gestureを視線目標へ合成する。"""

    def compose(
        self,
        *,
        selection: BodyAttentionSelection,
        ambient: BodyAmbientMotionSample,
        state: BodyInnerMotionState,
        attention: BodyAttentionIntent | None,
        gesture: BodyExpressionGestureSample,
    ) -> BodyGazeTarget:
        if selection.uses_candidate:
            target_x, target_y = selection.x, selection.y
        elif attention is not None and attention.behavior in {
            BodyAttentionBehavior.MAINTAIN,
            BodyAttentionBehavior.GLANCE,
        }:
            target_x, target_y = 0.0, 0.0
        elif attention is not None and attention.behavior is BodyAttentionBehavior.AVOID:
            direction = -1.0 if ambient.scan_x >= 0.0 else 1.0
            target_x = direction * (0.22 + attention.avoidance * 0.35)
            target_y = ambient.scan_y * 0.35
        else:
            target_x, target_y = ambient.scan_x, ambient.scan_y

        target_strength = 0.28 + state.curiosity * 0.40 + state.engagement * 0.22
        if selection.uses_candidate:
            target_strength += 0.18
        gaze_x = self._clamp(target_x * target_strength + ambient.head_noise * 0.12)
        gaze_y = self._clamp(target_y * target_strength + ambient.head_noise * 0.08)

        gaze_distance = min(1.0, math.hypot(gaze_x, gaze_y))
        eye_follow = attention.eye_follow if attention is not None else 1.0
        head_follow = (
            attention.head_follow
            if attention is not None
            else 0.28 + gaze_distance * 0.48 + state.engagement * 0.12
        )
        body_follow = (
            attention.body_follow
            if attention is not None
            else max(0.0, gaze_distance - 0.34)
            * (0.18 + state.confidence * 0.20)
        )

        return BodyGazeTarget(
            gaze_x=self._clamp(gaze_x * eye_follow),
            gaze_y=self._clamp(gaze_y * eye_follow),
            head_yaw=self._clamp(gaze_x * head_follow + gesture.head_yaw),
            head_pitch=self._clamp(
                gaze_y * head_follow
                + ambient.head_noise * 0.16
                + gesture.head_pitch
            ),
            head_roll=self._clamp(
                ambient.posture_noise * 0.12 + gesture.head_roll
            ),
            torso_yaw=self._clamp(gaze_x * body_follow),
        )

    @staticmethod
    def _clamp(value: float) -> float:
        return max(-1.0, min(1.0, value))
