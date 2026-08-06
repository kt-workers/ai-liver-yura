from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from collections.abc import Callable

from app.runtime.body_ambient_motion_generator import BodyAmbientMotionGenerator
from app.runtime.body_attention_selector import BodyAttentionSelector
from app.runtime.body_blink_scheduler import BodyBlinkScheduler
from app.runtime.body_breathing_oscillator import BodyBreathingOscillator
from app.runtime.body_expression_gesture_generator import (
    BodyExpressionGestureGenerator,
)
from app.runtime.body_external_constraint_player import (
    BodyExternalConstraintPlayer,
)
from app.runtime.body_gaze_target_composer import BodyGazeTargetComposer
from app.runtime.body_motion_state_projector import BodyMotionStateProjector
from app.runtime.body_pose_frame_assembler import BodyPoseFrameAssembler
from app.runtime.body_pose_integrator import BodyPoseIntegrator
from app.runtime.body_pose_target_composer import BodyPoseTargetComposer
from app.runtime.body_posture_target_composer import BodyPostureTargetComposer
from app.runtime.body_speech_mouth_driver import BodySpeechMouthDriver
from app.runtime.body_tick_clock import BodyTickClock


@dataclass(slots=True)
class BodyControllerComponents:
    """StateDrivenBodyControllerが呼び出す独立責務の集合。"""

    clock: BodyTickClock
    motion_projector: BodyMotionStateProjector
    attention_selector: BodyAttentionSelector
    ambient_motion: BodyAmbientMotionGenerator
    breathing: BodyBreathingOscillator
    blink: BodyBlinkScheduler
    expression_gesture: BodyExpressionGestureGenerator
    speech_mouth: BodySpeechMouthDriver
    external_constraint: BodyExternalConstraintPlayer
    gaze_composer: BodyGazeTargetComposer
    posture_composer: BodyPostureTargetComposer
    target_composer: BodyPoseTargetComposer
    integrator: BodyPoseIntegrator
    frame_assembler: BodyPoseFrameAssembler

    @classmethod
    def create(
        cls,
        *,
        tick_hz: float = 30.0,
        seed: int | None = None,
        monotonic_clock: Callable[[], float] = monotonic,
    ) -> BodyControllerComponents:
        return cls(
            clock=BodyTickClock(
                tick_hz=tick_hz,
                monotonic_clock=monotonic_clock,
            ),
            motion_projector=BodyMotionStateProjector(),
            attention_selector=BodyAttentionSelector(seed=seed),
            ambient_motion=BodyAmbientMotionGenerator(
                seed=None if seed is None else seed + 1
            ),
            breathing=BodyBreathingOscillator(),
            blink=BodyBlinkScheduler(seed=None if seed is None else seed + 2),
            expression_gesture=BodyExpressionGestureGenerator(),
            speech_mouth=BodySpeechMouthDriver(),
            external_constraint=BodyExternalConstraintPlayer(),
            gaze_composer=BodyGazeTargetComposer(),
            posture_composer=BodyPostureTargetComposer(),
            target_composer=BodyPoseTargetComposer(),
            integrator=BodyPoseIntegrator(),
            frame_assembler=BodyPoseFrameAssembler(),
        )
