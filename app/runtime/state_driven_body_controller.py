from __future__ import annotations

from app.domain.body_attention import BodyAttentionCandidate
from app.domain.body_expression_input import BodyExpressionInput
from app.domain.body_pose_dynamics import (
    BodyExternalConstraint,
    BodyPoseDynamicsState,
)
from app.domain.body_pose_frame import BodyPoseFrame
from app.domain.body_speech import SpeechPresentationRequest
from app.runtime.body_controller_components import BodyControllerComponents


class StateDrivenBodyController:
    """分離済みBody部品の呼び出し順だけを管理する薄いController。"""

    def __init__(
        self,
        initial_input: BodyExpressionInput,
        *,
        components: BodyControllerComponents | None = None,
        tick_hz: float = 30.0,
        seed: int | None = None,
    ) -> None:
        if not isinstance(initial_input, BodyExpressionInput):
            raise TypeError("initial_input must be BodyExpressionInput")
        self._input = initial_input
        self._components = components or BodyControllerComponents.create(
            tick_hz=tick_hz,
            seed=seed,
        )
        self._dynamics = BodyPoseDynamicsState()

    @property
    def tick_hz(self) -> float:
        return self._components.clock.tick_hz

    @property
    def expression_input(self) -> BodyExpressionInput:
        return self._input

    @property
    def dynamics_state(self) -> BodyPoseDynamicsState:
        return self._dynamics

    @property
    def active_constraint_id(self) -> str | None:
        return self._components.external_constraint.active_constraint_id

    @property
    def active_speech_id(self) -> str | None:
        return self._components.speech_mouth.active_presentation_id

    def update_expression_input(self, value: BodyExpressionInput) -> None:
        if not isinstance(value, BodyExpressionInput):
            raise TypeError("value must be BodyExpressionInput")
        self._input = value

    def set_attention_candidates(
        self,
        candidates: tuple[BodyAttentionCandidate, ...] | list[BodyAttentionCandidate],
    ) -> None:
        self._components.attention_selector.set_candidates(candidates)

    def apply_external_constraint(self, constraint: BodyExternalConstraint) -> None:
        self._components.external_constraint.apply(constraint)

    def clear_external_constraint(self) -> None:
        self._components.external_constraint.clear()

    def present_speech(
        self,
        request: SpeechPresentationRequest,
        *,
        energy: float = 0.5,
    ) -> None:
        self._components.speech_mouth.present(request, energy=energy)

    def clear_speech(self) -> None:
        self._components.speech_mouth.clear()

    def request_blink(self) -> None:
        self._components.blink.request_blink()

    def tick(
        self,
        *,
        timestamp_ms: int | None = None,
        dt_seconds: float | None = None,
    ) -> BodyPoseFrame:
        tick = self._components.clock.next(
            timestamp_ms=timestamp_ms,
            dt_seconds=dt_seconds,
        )
        motion_state = self._components.motion_projector.project(self._input)
        attention = self._components.attention_selector.step(
            dt_seconds=tick.dt_seconds,
            state=motion_state,
            intent=self._input.attention_intent,
        )
        ambient = self._components.ambient_motion.step(
            dt_seconds=tick.dt_seconds,
            state=motion_state,
        )
        breathing = self._components.breathing.step(
            dt_seconds=tick.dt_seconds,
            state=motion_state,
        )
        blink = self._components.blink.step(
            dt_seconds=tick.dt_seconds,
            state=motion_state,
        )
        gesture = self._components.expression_gesture.step(
            dt_seconds=tick.dt_seconds,
            expression=self._input.expression_overlay,
        )
        speech = self._components.speech_mouth.step(dt_seconds=tick.dt_seconds)
        constraint = self._components.external_constraint.step(
            dt_seconds=tick.dt_seconds
        )
        gaze = self._components.gaze_composer.compose(
            selection=attention,
            ambient=ambient,
            state=motion_state,
            attention=self._input.attention_intent,
            gesture=gesture,
        )
        posture = self._components.posture_composer.compose(
            value=self._input,
            state=motion_state,
            ambient=ambient,
            breathing=breathing,
        )
        target = self._components.target_composer.compose(
            value=self._input,
            gaze=gaze,
            posture=posture,
            blink=blink,
            speech=speech,
            constraint=constraint,
            attention_target_id=attention.target_id,
            attention_dwell_ms=attention.dwell_ms,
        )
        self._dynamics = self._components.integrator.step(
            state=self._dynamics,
            target=target.pose,
            dt_seconds=tick.dt_seconds,
        )
        return self._components.frame_assembler.assemble(
            sequence=tick.sequence,
            timestamp_ms=tick.timestamp_ms,
            dynamics=self._dynamics,
            inner_state=motion_state,
            target=target,
        )
