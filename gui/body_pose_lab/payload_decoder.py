from __future__ import annotations

from app.domain.body_activity_context import BodyActivityContext
from app.domain.body_attention import BodyAttentionCandidate
from app.domain.body_pose_dynamics import BodyExternalConstraint
from app.domain.body_pose_frame import BodyPoseFrame
from app.domain.body_speech import SpeechPresentationRequest
from app.domain.emotions.emotion_state import EmotionState
from gui.body_pose_lab.body_input_decoder import BodyPoseLabBodyInputDecoder
from gui.body_pose_lab.emotion_context_decoder import (
    BodyPoseLabEmotionContextDecoder,
)
from gui.body_pose_lab.frame_payload_decoder import BodyPoseLabFramePayloadDecoder
from gui.body_pose_lab.payload_primitives import (
    BodyPoseLabPayloadError,
    BodyPoseLabPayloadReader,
)

__all__ = ["BodyPoseLabPayloadDecoder", "BodyPoseLabPayloadError"]


class BodyPoseLabPayloadDecoder:
    """責務別Decoderを従来APIで公開する薄いFacade。"""

    def __init__(
        self,
        *,
        emotion_context: BodyPoseLabEmotionContextDecoder | None = None,
        body_input: BodyPoseLabBodyInputDecoder | None = None,
        frame: BodyPoseLabFramePayloadDecoder | None = None,
    ) -> None:
        reader = BodyPoseLabPayloadReader()
        self._emotion_context = emotion_context or BodyPoseLabEmotionContextDecoder(
            reader
        )
        self._body_input = body_input or BodyPoseLabBodyInputDecoder(reader)
        self._frame = frame or BodyPoseLabFramePayloadDecoder(reader)

    def decode_emotion(self, value: object) -> EmotionState:
        return self._emotion_context.decode_emotion(value)

    def decode_activity_context(self, value: object) -> BodyActivityContext:
        return self._emotion_context.decode_activity_context(value)

    def decode_attention_candidates(
        self,
        value: object,
    ) -> tuple[BodyAttentionCandidate, ...]:
        return self._body_input.decode_attention_candidates(value)

    def decode_external_constraint(self, value: object) -> BodyExternalConstraint:
        return self._body_input.decode_external_constraint(value)

    def decode_speech(
        self,
        value: object,
    ) -> tuple[SpeechPresentationRequest, float | None]:
        return self._body_input.decode_speech(value)

    def decode_frame(self, value: object) -> BodyPoseFrame:
        return self._frame.decode(value)
