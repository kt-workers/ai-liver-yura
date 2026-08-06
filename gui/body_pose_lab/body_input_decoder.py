from __future__ import annotations

from collections.abc import Mapping

from app.domain.body_attention import BodyAttentionCandidate
from app.domain.body_pose_dynamics import (
    BodyExternalConstraint,
    BodyPoseAxis,
    BodyPoseConstraintTarget,
)
from app.domain.body_speech import SpeechPresentationRequest
from gui.body_pose_lab.payload_primitives import (
    BodyPoseLabPayloadError,
    BodyPoseLabPayloadReader,
)


class BodyPoseLabBodyInputDecoder:
    """注意候補・一時制約・発話入力のJSON境界を担当する。"""

    def __init__(self, reader: BodyPoseLabPayloadReader | None = None) -> None:
        self._reader = reader or BodyPoseLabPayloadReader()

    def decode_attention_candidates(
        self,
        value: object,
    ) -> tuple[BodyAttentionCandidate, ...]:
        source = value
        if isinstance(value, Mapping):
            source = value.get("candidates", ())
        items = self._reader.sequence(source, "candidates")
        if len(items) > 32:
            raise BodyPoseLabPayloadError("at most 32 candidates are supported")
        candidates: list[BodyAttentionCandidate] = []
        for index, item in enumerate(items):
            payload = self._reader.mapping(item, f"candidates[{index}]")
            try:
                candidates.append(
                    BodyAttentionCandidate(
                        candidate_id=str(payload.get("candidate_id") or ""),
                        x=self._reader.number(payload.get("x"), "x"),
                        y=self._reader.number(payload.get("y"), "y"),
                        salience=self._reader.number(
                            payload.get("salience", 0.5),
                            "salience",
                        ),
                        novelty=self._reader.number(
                            payload.get("novelty", 0.0),
                            "novelty",
                        ),
                        threat=self._reader.number(
                            payload.get("threat", 0.0),
                            "threat",
                        ),
                        relevance=self._reader.number(
                            payload.get("relevance", 0.5),
                            "relevance",
                        ),
                        stability=self._reader.number(
                            payload.get("stability", 0.7),
                            "stability",
                        ),
                    )
                )
            except (TypeError, ValueError) as error:
                raise BodyPoseLabPayloadError(str(error)) from error
        return tuple(candidates)

    def decode_external_constraint(self, value: object) -> BodyExternalConstraint:
        payload = self._reader.mapping(value, "external_constraint")
        target_items = self._reader.sequence(payload.get("targets"), "targets")
        targets: list[BodyPoseConstraintTarget] = []
        for index, item in enumerate(target_items):
            target = self._reader.mapping(item, f"targets[{index}]")
            try:
                targets.append(
                    BodyPoseConstraintTarget(
                        axis=BodyPoseAxis(str(target.get("axis") or "")),
                        value=self._reader.number(target.get("value"), "value"),
                        weight=self._reader.number(
                            target.get("weight", 1.0),
                            "weight",
                        ),
                    )
                )
            except (TypeError, ValueError) as error:
                raise BodyPoseLabPayloadError(str(error)) from error
        try:
            return BodyExternalConstraint(
                constraint_id=str(payload.get("constraint_id") or ""),
                targets=tuple(targets),
                duration_ms=self._reader.integer(
                    payload.get("duration_ms"),
                    "duration_ms",
                ),
                attack_ratio=self._reader.number(
                    payload.get("attack_ratio", 0.18),
                    "attack_ratio",
                ),
                release_ratio=self._reader.number(
                    payload.get("release_ratio", 0.24),
                    "release_ratio",
                ),
            )
        except (TypeError, ValueError) as error:
            raise BodyPoseLabPayloadError(str(error)) from error

    def decode_speech(
        self,
        value: object,
    ) -> tuple[SpeechPresentationRequest, float | None]:
        payload = self._reader.mapping(value, "speech")
        energy_value = payload.get("energy")
        energy = (
            None
            if energy_value is None
            else self._reader.number(energy_value, "energy")
        )
        if energy is not None and not 0.0 <= energy <= 1.0:
            raise BodyPoseLabPayloadError("energy must be between 0 and 1")
        try:
            return (
                SpeechPresentationRequest(
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
                    duration_ms=self._reader.integer(
                        payload.get("duration_ms"),
                        "duration_ms",
                    ),
                    presentation_id=str(
                        payload.get("presentation_id") or "body-pose-lab-speech"
                    ),
                ),
                energy,
            )
        except (TypeError, ValueError) as error:
            raise BodyPoseLabPayloadError(str(error)) from error
