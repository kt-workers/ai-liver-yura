from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from app.domain.body_activity_context import BodyActivityContext
from app.domain.body_attention import BodyAttentionCandidate
from app.domain.body_pose_dynamics import BodyExternalConstraint
from app.domain.body_pose_frame import BodyPoseFrame
from app.domain.body_speech import SpeechPresentationRequest
from app.domain.emotions.emotion_state import EmotionState
from app.runtime.body_expression_input_builder import BodyExpressionInputBuilder
from app.runtime.state_driven_body_controller import StateDrivenBodyController
from gui.body_pose_lab.frame_hub import BodyPoseLabFrameHub


@dataclass(frozen=True, slots=True)
class BodyPoseLabApplicationSnapshot:
    emotion: EmotionState
    activity_context: BodyActivityContext
    attention_candidates: tuple[BodyAttentionCandidate, ...]
    active_constraint_id: str | None
    active_speech_id: str | None
    frame_sequence: int | None

    def as_payload(self) -> dict[str, object]:
        reactive = self.emotion.reactive
        context = self.activity_context
        return {
            "emotion": {
                "mood": self.emotion.mood.value,
                "arousal": self.emotion.arousal,
                "valence": self.emotion.valence,
                "talkativeness": self.emotion.talkativeness,
                "reactive": reactive.as_dict(),
            },
            "activity_context": {
                "source_activity_id": context.source_activity_id,
                "attention_target": context.attention_target,
                "engagement": context.engagement,
                "posture_tendency": context.posture_tendency.value,
                "movement_energy": context.movement_energy,
                "gaze_freedom": context.gaze_freedom,
                "interaction_intention": (
                    context.interaction_intention.as_context()
                    if context.interaction_intention is not None
                    else None
                ),
            },
            "attention_candidates": [
                candidate.as_payload() for candidate in self.attention_candidates
            ],
            "active_constraint_id": self.active_constraint_id,
            "active_speech_id": self.active_speech_id,
            "frame_sequence": self.frame_sequence,
        }


class BodyPoseLabApplicationService:
    """Lab入力を型付きBody契約へ適用し、Controllerを1Tick進める。"""

    def __init__(
        self,
        *,
        controller: StateDrivenBodyController,
        frame_hub: BodyPoseLabFrameHub,
        initial_emotion: EmotionState,
        initial_context: BodyActivityContext,
        input_builder: BodyExpressionInputBuilder | None = None,
        frame_source: str = "body-pose-lab-local",
    ) -> None:
        if not isinstance(controller, StateDrivenBodyController):
            raise TypeError("controller must be StateDrivenBodyController")
        if not isinstance(frame_hub, BodyPoseLabFrameHub):
            raise TypeError("frame_hub must be BodyPoseLabFrameHub")
        if not isinstance(initial_emotion, EmotionState):
            raise TypeError("initial_emotion must be EmotionState")
        if not isinstance(initial_context, BodyActivityContext):
            raise TypeError("initial_context must be BodyActivityContext")
        self._controller = controller
        self._frame_hub = frame_hub
        self._emotion = initial_emotion
        self._context = initial_context
        self._input_builder = input_builder or BodyExpressionInputBuilder()
        self._attention_candidates: tuple[BodyAttentionCandidate, ...] = ()
        self._frame_source = frame_source
        self._last_frame: BodyPoseFrame | None = None
        self._lock = RLock()

    @property
    def tick_hz(self) -> float:
        return self._controller.tick_hz

    def update_emotion(self, emotion: EmotionState) -> None:
        if not isinstance(emotion, EmotionState):
            raise TypeError("emotion must be EmotionState")
        with self._lock:
            self._emotion = emotion

    def update_activity_context(self, context: BodyActivityContext) -> None:
        if not isinstance(context, BodyActivityContext):
            raise TypeError("context must be BodyActivityContext")
        with self._lock:
            self._context = context

    def update_attention_candidates(
        self,
        candidates: tuple[BodyAttentionCandidate, ...] | list[BodyAttentionCandidate],
    ) -> None:
        normalized = tuple(candidates)
        if not all(
            isinstance(candidate, BodyAttentionCandidate) for candidate in normalized
        ):
            raise TypeError("candidates must contain BodyAttentionCandidate values")
        with self._lock:
            self._attention_candidates = normalized
            self._controller.set_attention_candidates(normalized)

    def apply_external_constraint(self, constraint: BodyExternalConstraint) -> None:
        if not isinstance(constraint, BodyExternalConstraint):
            raise TypeError("constraint must be BodyExternalConstraint")
        with self._lock:
            self._controller.apply_external_constraint(constraint)

    def clear_external_constraint(self) -> None:
        with self._lock:
            self._controller.clear_external_constraint()

    def present_speech(
        self,
        request: SpeechPresentationRequest,
        *,
        energy: float | None = None,
    ) -> None:
        if not isinstance(request, SpeechPresentationRequest):
            raise TypeError("request must be SpeechPresentationRequest")
        with self._lock:
            resolved_energy = (
                max(self._context.movement_energy, self._emotion.arousal)
                if energy is None
                else energy
            )
            self._controller.present_speech(request, energy=resolved_energy)

    def request_blink(self) -> None:
        with self._lock:
            self._controller.request_blink()

    def tick_once(
        self,
        *,
        timestamp_ms: int | None = None,
        dt_seconds: float | None = None,
    ) -> BodyPoseFrame:
        with self._lock:
            expression_input = self._input_builder.build(
                emotion=self._emotion,
                context=self._context,
            )
            self._controller.update_expression_input(expression_input)
            frame = self._controller.tick(
                timestamp_ms=timestamp_ms,
                dt_seconds=dt_seconds,
            )
            self._last_frame = frame
        self._frame_hub.publish(frame, source=self._frame_source)
        return frame

    def snapshot(self) -> BodyPoseLabApplicationSnapshot:
        with self._lock:
            return BodyPoseLabApplicationSnapshot(
                emotion=self._emotion,
                activity_context=self._context,
                attention_candidates=self._attention_candidates,
                active_constraint_id=self._controller.active_constraint_id,
                active_speech_id=self._controller.active_speech_id,
                frame_sequence=(
                    self._last_frame.sequence if self._last_frame is not None else None
                ),
            )
