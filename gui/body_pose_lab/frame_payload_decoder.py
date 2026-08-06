from __future__ import annotations

from collections.abc import Mapping

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
from app.domain.body_pose_frame import BodyPoseFrame
from app.domain.body_skeleton import BodyJointPose
from gui.body_pose_lab.payload_primitives import (
    BodyPoseLabPayloadError,
    BodyPoseLabPayloadReader,
)


class BodyPoseLabFramePayloadDecoder:
    """BodyPoseFrame Schemaと幾何・骨格Payloadの復元だけを担当する。"""

    def __init__(self, reader: BodyPoseLabPayloadReader | None = None) -> None:
        self._reader = reader or BodyPoseLabPayloadReader()

    def decode(self, value: object) -> BodyPoseFrame:
        payload = self._reader.mapping(value, "body_pose_frame")
        try:
            return BodyPoseFrame(
                schema_version=self._reader.integer(
                    payload.get("schema_version", 2),
                    "schema_version",
                ),
                sequence=self._reader.integer(
                    payload.get("sequence"),
                    "sequence",
                ),
                timestamp_ms=self._reader.integer(
                    payload.get("timestamp_ms"),
                    "timestamp_ms",
                ),
                coordinate_space=BodyCoordinateSpace(
                    str(
                        payload.get(
                            "coordinate_space",
                            BodyCoordinateSpace.RIGHT_HANDED_Y_UP.value,
                        )
                    )
                ),
                pose=BodyTrackingPose(
                    **self._reader.dataclass_numbers(
                        BodyTrackingPose,
                        self._reader.mapping(payload.get("pose"), "pose"),
                    )
                ),
                velocity=BodyTrackingVelocity(
                    **self._reader.dataclass_numbers(
                        BodyTrackingVelocity,
                        self._reader.mapping(
                            payload.get("velocity", {}),
                            "velocity",
                        ),
                    )
                ),
                inner_state=BodyInnerMotionState(
                    **self._reader.dataclass_numbers(
                        BodyInnerMotionState,
                        self._reader.mapping(
                            payload.get("inner_state", {}),
                            "inner_state",
                        ),
                    )
                ),
                root_transform=self._decode_transform(
                    self._reader.mapping(
                        payload.get("root_transform", {}),
                        "root_transform",
                    )
                ),
                joints=tuple(
                    self._decode_joint(item, index)
                    for index, item in enumerate(
                        self._reader.sequence(payload.get("joints", ()), "joints")
                    )
                ),
                blend_shapes=tuple(
                    self._decode_blend_shape(item, index)
                    for index, item in enumerate(
                        self._reader.sequence(
                            payload.get("blend_shapes", ()),
                            "blend_shapes",
                        )
                    )
                ),
                gaze_vector=self._decode_gaze(
                    self._reader.mapping(
                        payload.get("gaze_vector", {}),
                        "gaze_vector",
                    )
                ),
                attention_target_id=self._reader.optional_string(
                    payload.get("attention_target_id"),
                    "attention_target_id",
                ),
                attention_dwell_ms=self._reader.integer(
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
                self._reader.mapping(payload.get("position", {}), "position")
            ),
            rotation=self._decode_quaternion(
                self._reader.mapping(payload.get("rotation", {}), "rotation")
            ),
            scale=self._decode_vector(
                self._reader.mapping(
                    payload.get("scale", {"x": 1.0, "y": 1.0, "z": 1.0}),
                    "scale",
                )
            ),
        )

    def _decode_joint(self, value: object, index: int) -> BodyJointPose:
        payload = self._reader.mapping(value, f"joints[{index}]")
        position_payload = payload.get("position")
        return BodyJointPose(
            joint_id=str(payload.get("joint_id") or ""),
            rotation=self._decode_quaternion(
                self._reader.mapping(payload.get("rotation", {}), "rotation")
            ),
            position=(
                self._decode_vector(
                    self._reader.mapping(position_payload, "position")
                )
                if position_payload is not None
                else None
            ),
            confidence=self._reader.number(
                payload.get("confidence", 1.0),
                "confidence",
            ),
        )

    def _decode_blend_shape(self, value: object, index: int) -> BodyBlendShape:
        payload = self._reader.mapping(value, f"blend_shapes[{index}]")
        return BodyBlendShape(
            name=str(payload.get("name") or ""),
            value=self._reader.number(payload.get("value"), "value"),
        )

    def _decode_gaze(self, payload: Mapping[str, object]) -> BodyGazeVector:
        return BodyGazeVector(
            origin=self._decode_vector(
                self._reader.mapping(
                    payload.get("origin", {"x": 0.0, "y": 1.55, "z": 0.0}),
                    "origin",
                )
            ),
            direction=self._decode_vector(
                self._reader.mapping(
                    payload.get("direction", {"x": 0.0, "y": 0.0, "z": 1.0}),
                    "direction",
                )
            ),
        )

    def _decode_vector(self, payload: Mapping[str, object]) -> BodyVector3:
        return BodyVector3(
            x=self._reader.number(payload.get("x", 0.0), "x"),
            y=self._reader.number(payload.get("y", 0.0), "y"),
            z=self._reader.number(payload.get("z", 0.0), "z"),
        )

    def _decode_quaternion(self, payload: Mapping[str, object]) -> BodyQuaternion:
        return BodyQuaternion(
            x=self._reader.number(payload.get("x", 0.0), "x"),
            y=self._reader.number(payload.get("y", 0.0), "y"),
            z=self._reader.number(payload.get("z", 0.0), "z"),
            w=self._reader.number(payload.get("w", 1.0), "w"),
        )
