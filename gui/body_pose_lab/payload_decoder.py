from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import fields
from typing import Any

from app.domain.body_activity_context import BodyActivityContext, BodyPostureTendency
from app.domain.body_attention import BodyAttentionCandidate
from app.domain.body_auxiliary_projection import (
    BodyTrackingPose,
    BodyTrackingVelocity,
)
from app.domain.body_blend_shape import BodyBlendShape
from app.domain.body_geometry import (
    BodyCoordinateSpace,
    BodyGazeVector,
    BodyQuaternion,
    BodyTransform3D,
    BodyVector3,
)
from app.domain.body_motion_state import BodyInnerMotionState
from app.domain.body_pose_dynamics import (
    BodyExternalConstraint,
    BodyPoseAxis,
    BodyPoseConstraintTarget,
)
from app.domain.body_pose_frame import BodyPoseFrame
from app.domain.body_skeleton import BodyJointPose
from app.domain.body_speech import SpeechPresentationRequest
from app.domain.emotions.emotion_state import (
    EmotionState,
    MoodType,
    ReactiveEmotionState,
)
from app.domain.interaction_intention import InteractionIntention


class BodyPoseLabPayloadError(ValueError):
    """Labの公開JSON境界で検出した安全な入力エラー。"""


class BodyPoseLabPayloadDecoder:
    """JSON互換値を型付きBody Domain契約へ変換する。"""

    def decode_emotion(self, value: object) -> EmotionState:
        payload = self._mapping(value, "emotion")
        reactive_payload = self._mapping(payload.get("reactive", {}), "reactive")
        try:
            return EmotionState(
                mood=MoodType(str(payload.get("mood", "neutral"))),
                arousal=self._number(payload.get("arousal", 0.5), "arousal"),
                valence=self._number(payload.get("valence", 0.0), "valence"),
                talkativeness=self._number(
                    payload.get("talkativeness", 0.5),
                    "talkativeness",
                ),
                reactive=ReactiveEmotionState(
                    **self._dataclass_numbers(
                        ReactiveEmotionState,
                        reactive_payload,
                    )
                ),
            )
        except (TypeError, ValueError) as error:
            raise BodyPoseLabPayloadError(str(error)) from error

    def decode_activity_context(self, value: object) -> BodyActivityContext:
        payload = self._mapping(value, "activity_context")
        intention_payload = payload.get("interaction_intention")
        intention = InteractionIntention.from_context(intention_payload)
        if intention_payload is not None and intention is None:
            raise BodyPoseLabPayloadError("interaction_intention is invalid")
        try:
            return BodyActivityContext(
                source_activity_id=str(
                    payload.get("source_activity_id") or "body-pose-lab"
                ),
                attention_target=self._optional_string(
                    payload.get("attention_target")
                ),
                engagement=self._number(
                    payload.get("engagement", 0.5),
                    "engagement",
                ),
                posture_tendency=BodyPostureTendency(
                    str(payload.get("posture_tendency", "neutral"))
                ),
                movement_energy=self._number(
                    payload.get("movement_energy", 0.35),
                    "movement_energy",
                ),
                gaze_freedom=self._number(
                    payload.get("gaze_freedom", 0.5),
                    "gaze_freedom",
                ),
                interaction_intention=intention,
            )
        except (TypeError, ValueError) as error:
            raise BodyPoseLabPayloadError(str(error)) from error

    def decode_attention_candidates(
        self,
        value: object,
    ) -> tuple[BodyAttentionCandidate, ...]:
        source = value
        if isinstance(value, Mapping):
            source = value.get("candidates", ())
        items = self._sequence(source, "candidates")
        if len(items) > 32:
            raise BodyPoseLabPayloadError("at most 32 candidates are supported")
        candidates: list[BodyAttentionCandidate] = []
        for index, item in enumerate(items):
            payload = self._mapping(item, f"candidates[{index}]")
            try:
                candidates.append(
                    BodyAttentionCandidate(
                        candidate_id=str(payload.get("candidate_id") or ""),
                        x=self._number(payload.get("x"), "x"),
                        y=self._number(payload.get("y"), "y"),
                        salience=self._number(
                            payload.get("salience", 0.5), "salience"
                        ),
                        novelty=self._number(
                            payload.get("novelty", 0.0), "novelty"
                        ),
                        threat=self._number(
                            payload.get("threat", 0.0), "threat"
                        ),
                        relevance=self._number(
                            payload.get("relevance", 0.5), "relevance"
                        ),
                        stability=self._number(
                            payload.get("stability", 0.7), "stability"
                        ),
                    )
                )
            except (TypeError, ValueError) as error:
                raise BodyPoseLabPayloadError(str(error)) from error
        return tuple(candidates)

    def decode_external_constraint(self, value: object) -> BodyExternalConstraint:
        payload = self._mapping(value, "external_constraint")
        target_items = self._sequence(payload.get("targets"), "targets")
        targets: list[BodyPoseConstraintTarget] = []
        for index, item in enumerate(target_items):
            target = self._mapping(item, f"targets[{index}]")
            try:
                targets.append(
                    BodyPoseConstraintTarget(
                        axis=BodyPoseAxis(str(target.get("axis") or "")),
                        value=self._number(target.get("value"), "value"),
                        weight=self._number(target.get("weight", 1.0), "weight"),
                    )
                )
            except (TypeError, ValueError) as error:
                raise BodyPoseLabPayloadError(str(error)) from error
        try:
            return BodyExternalConstraint(
                constraint_id=str(payload.get("constraint_id") or ""),
                targets=tuple(targets),
                duration_ms=self._integer(payload.get("duration_ms"), "duration_ms"),
                attack_ratio=self._number(
                    payload.get("attack_ratio", 0.18), "attack_ratio"
                ),
                release_ratio=self._number(
                    payload.get("release_ratio", 0.24), "release_ratio"
                ),
            )
        except (TypeError, ValueError) as error:
            raise BodyPoseLabPayloadError(str(error)) from error

    def decode_speech(self, value: object) -> tuple[SpeechPresentationRequest, float | None]:
        payload = self._mapping(value, "speech")
        energy_value = payload.get("energy")
        energy = (
            None if energy_value is None else self._number(energy_value, "energy")
        )
        try:
            request = SpeechPresentationRequest(
                source_activity_id=str(
                    payload.get("source_activity_id") or "body-pose-lab"
                ),
                output_unit_id=str(
                    payload.get("output_unit_id") or "body-pose-lab-speech"
                ),
                text=str(payload.get("text") or "body pose lab speech"),
                audio_reference=str(
                    payload.get("audio_reference") or "lab://speech"
                ),
                duration_ms=self._integer(
                    payload.get("duration_ms"),
                    "duration_ms",
                ),
                presentation_id=str(
                    payload.get("presentation_id") or "body-pose-lab-speech"
                ),
            )
        except (TypeError, ValueError) as error:
            raise BodyPoseLabPayloadError(str(error)) from error
        if energy is not None and not 0.0 <= energy <= 1.0:
            raise BodyPoseLabPayloadError("energy must be between 0 and 1")
        return request, energy

    def decode_frame(self, value: object) -> BodyPoseFrame:
        payload = self._mapping(value, "body_pose_frame")
        try:
            pose = BodyTrackingPose(
                **self._dataclass_numbers(
                    BodyTrackingPose,
                    self._mapping(payload.get("pose"), "pose"),
                )
            )
            velocity = BodyTrackingVelocity(
                **self._dataclass_numbers(
                    BodyTrackingVelocity,
                    self._mapping(payload.get("velocity", {}), "velocity"),
                )
            )
            inner_state = BodyInnerMotionState(
                **self._dataclass_numbers(
                    BodyInnerMotionState,
                    self._mapping(payload.get("inner_state", {}), "inner_state"),
                )
            )
            root_transform = self._decode_transform(
                self._mapping(payload.get("root_transform", {}), "root_transform")
            )
            joints = tuple(
                self._decode_joint(item, index)
                for index, item in enumerate(
                    self._sequence(payload.get("joints", ()), "joints")
                )
            )
            blend_shapes = tuple(
                self._decode_blend_shape(item, index)
                for index, item in enumerate(
                    self._sequence(payload.get("blend_shapes", ()), "blend_shapes")
                )
            )
            gaze_vector = self._decode_gaze(
                self._mapping(payload.get("gaze_vector", {}), "gaze_vector")
            )
            return BodyPoseFrame(
                schema_version=self._integer(
                    payload.get("schema_version", 2), "schema_version"
                ),
                sequence=self._integer(payload.get("sequence"), "sequence"),
                timestamp_ms=self._integer(
                    payload.get("timestamp_ms"), "timestamp_ms"
                ),
                coordinate_space=BodyCoordinateSpace(
                    str(payload.get("coordinate_space", "right_handed_y_up"))
                ),
                pose=pose,
                velocity=velocity,
                inner_state=inner_state,
                root_transform=root_transform,
                joints=joints,
                blend_shapes=blend_shapes,
                gaze_vector=gaze_vector,
                attention_target_id=self._optional_string(
                    payload.get("attention_target_id")
                ),
                attention_dwell_ms=self._integer(
                    payload.get("attention_dwell_ms", 0),
                    "attention_dwell_ms",
                ),
            )
        except BodyPoseLabPayloadError:
            raise
        except (TypeError, ValueError) as error:
            raise BodyPoseLabPayloadError(str(error)) from error

    def _decode_transform(self, payload: Mapping[str, object]) -> BodyTransform3D:
        return BodyTransform3D(
            position=self._decode_vector(
                self._mapping(payload.get("position", {}), "position")
            ),
            rotation=self._decode_quaternion(
                self._mapping(payload.get("rotation", {}), "rotation")
            ),
            scale=self._decode_vector(
                self._mapping(
                    payload.get("scale", {"x": 1.0, "y": 1.0, "z": 1.0}),
                    "scale",
                )
            ),
        )

    def _decode_joint(self, value: object, index: int) -> BodyJointPose:
        payload = self._mapping(value, f"joints[{index}]")
        position_payload = payload.get("position")
        return BodyJointPose(
            joint_id=str(payload.get("joint_id") or ""),
            rotation=self._decode_quaternion(
                self._mapping(payload.get("rotation", {}), "rotation")
            ),
            position=(
                self._decode_vector(self._mapping(position_payload, "position"))
                if position_payload is not None
                else None
            ),
            confidence=self._number(payload.get("confidence", 1.0), "confidence"),
        )

    def _decode_blend_shape(self, value: object, index: int) -> BodyBlendShape:
        payload = self._mapping(value, f"blend_shapes[{index}]")
        return BodyBlendShape(
            name=str(payload.get("name") or ""),
            value=self._number(payload.get("value"), "value"),
        )

    def _decode_gaze(self, payload: Mapping[str, object]) -> BodyGazeVector:
        return BodyGazeVector(
            origin=self._decode_vector(
                self._mapping(
                    payload.get("origin", {"x": 0.0, "y": 1.55, "z": 0.0}),
                    "origin",
                )
            ),
            direction=self._decode_vector(
                self._mapping(
                    payload.get("direction", {"x": 0.0, "y": 0.0, "z": 1.0}),
                    "direction",
                )
            ),
        )

    def _decode_vector(self, payload: Mapping[str, object]) -> BodyVector3:
        return BodyVector3(
            x=self._number(payload.get("x", 0.0), "x"),
            y=self._number(payload.get("y", 0.0), "y"),
            z=self._number(payload.get("z", 0.0), "z"),
        )

    def _decode_quaternion(self, payload: Mapping[str, object]) -> BodyQuaternion:
        return BodyQuaternion(
            x=self._number(payload.get("x", 0.0), "x"),
            y=self._number(payload.get("y", 0.0), "y"),
            z=self._number(payload.get("z", 0.0), "z"),
            w=self._number(payload.get("w", 1.0), "w"),
        )

    def _dataclass_numbers(
        self,
        target: type[Any],
        payload: Mapping[str, object],
    ) -> dict[str, float]:
        return {
            field.name: self._number(payload[field.name], field.name)
            for field in fields(target)
            if field.name in payload
        }

    @staticmethod
    def _mapping(value: object, name: str) -> Mapping[str, object]:
        if not isinstance(value, Mapping):
            raise BodyPoseLabPayloadError(f"{name} must be an object")
        return value

    @staticmethod
    def _sequence(value: object, name: str) -> Sequence[object]:
        if isinstance(value, (str, bytes, bytearray)) or not isinstance(
            value, Sequence
        ):
            raise BodyPoseLabPayloadError(f"{name} must be an array")
        return value

    @staticmethod
    def _number(value: object, name: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise BodyPoseLabPayloadError(f"{name} must be a number")
        return float(value)

    @staticmethod
    def _integer(value: object, name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise BodyPoseLabPayloadError(f"{name} must be an integer")
        return value

    @staticmethod
    def _optional_string(value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise BodyPoseLabPayloadError("optional text value must be a string")
        normalized = value.strip()
        return normalized or None
