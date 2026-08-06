from __future__ import annotations

from app.domain.body_activity_context import BodyActivityContext, BodyPostureTendency
from app.domain.emotions.emotion_state import (
    EmotionState,
    MoodType,
    ReactiveEmotionState,
)
from app.domain.interaction_intention import InteractionIntention
from gui.body_pose_lab.payload_primitives import (
    BodyPoseLabPayloadError,
    BodyPoseLabPayloadReader,
)


class BodyPoseLabEmotionContextDecoder:
    """EmotionとActivity ContextのJSON境界だけを担当する。"""

    def __init__(self, reader: BodyPoseLabPayloadReader | None = None) -> None:
        self._reader = reader or BodyPoseLabPayloadReader()

    def decode_emotion(self, value: object) -> EmotionState:
        payload = self._reader.mapping(value, "emotion")
        reactive_payload = self._reader.mapping(
            payload.get("reactive", {}),
            "reactive",
        )
        try:
            return EmotionState(
                mood=MoodType(str(payload.get("mood", "neutral"))),
                arousal=self._reader.number(
                    payload.get("arousal", 0.5),
                    "arousal",
                ),
                valence=self._reader.number(
                    payload.get("valence", 0.0),
                    "valence",
                ),
                talkativeness=self._reader.number(
                    payload.get("talkativeness", 0.5),
                    "talkativeness",
                ),
                reactive=ReactiveEmotionState(
                    **self._reader.dataclass_numbers(
                        ReactiveEmotionState,
                        reactive_payload,
                    )
                ),
            )
        except (TypeError, ValueError) as error:
            raise BodyPoseLabPayloadError(str(error)) from error

    def decode_activity_context(self, value: object) -> BodyActivityContext:
        payload = self._reader.mapping(value, "activity_context")
        intention_payload = payload.get("interaction_intention")
        intention = InteractionIntention.from_context(intention_payload)
        if intention_payload is not None and intention is None:
            raise BodyPoseLabPayloadError("interaction_intention is invalid")
        try:
            return BodyActivityContext(
                source_activity_id=str(
                    payload.get("source_activity_id") or "body-pose-lab"
                ),
                attention_target=self._reader.optional_string(
                    payload.get("attention_target"),
                    "attention_target",
                ),
                engagement=self._reader.number(
                    payload.get("engagement", 0.5),
                    "engagement",
                ),
                posture_tendency=BodyPostureTendency(
                    str(payload.get("posture_tendency", "neutral"))
                ),
                movement_energy=self._reader.number(
                    payload.get("movement_energy", 0.35),
                    "movement_energy",
                ),
                gaze_freedom=self._reader.number(
                    payload.get("gaze_freedom", 0.5),
                    "gaze_freedom",
                ),
                interaction_intention=intention,
            )
        except (TypeError, ValueError) as error:
            raise BodyPoseLabPayloadError(str(error)) from error
