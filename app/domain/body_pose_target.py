from __future__ import annotations

from dataclasses import dataclass

from app.domain.body_affect import BodyFacialAffectTarget
from app.domain.body_auxiliary_projection import BodyTrackingPose
from app.domain.body_value_validation import non_negative_integer, normalized_identifier


@dataclass(frozen=True, slots=True)
class BodyPoseTarget:
    """時間積分前の正規化Pose目標と顔表現メタデータ。"""

    pose: BodyTrackingPose
    facial_target: BodyFacialAffectTarget
    attention_target_id: str | None = None
    attention_dwell_ms: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.pose, BodyTrackingPose):
            raise TypeError("pose must be BodyTrackingPose")
        if not isinstance(self.facial_target, BodyFacialAffectTarget):
            raise TypeError("facial_target must be BodyFacialAffectTarget")
        if self.attention_target_id is not None:
            object.__setattr__(
                self,
                "attention_target_id",
                normalized_identifier(
                    self.attention_target_id,
                    "attention_target_id",
                ),
            )
        object.__setattr__(
            self,
            "attention_dwell_ms",
            non_negative_integer(self.attention_dwell_ms, "attention_dwell_ms"),
        )
