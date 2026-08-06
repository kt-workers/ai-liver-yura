from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.domain.body_value_validation import bounded_number, normalized_identifier
from app.domain.interaction_intention import InteractionIntention


class BodyPostureTendency(str, Enum):
    """Activity中に維持する高レベルな姿勢傾向。"""

    NEUTRAL = "neutral"
    OPEN = "open"
    CLOSED = "closed"
    FORWARD = "forward"
    WITHDRAWN = "withdrawn"


@dataclass(frozen=True, slots=True)
class BodyActivityContext:
    """ActivityがBodyへ継続的に提示する非Pose文脈。"""

    source_activity_id: str
    attention_target: str | None = None
    engagement: float = 0.5
    posture_tendency: BodyPostureTendency = BodyPostureTendency.NEUTRAL
    movement_energy: float = 0.35
    gaze_freedom: float = 0.5
    interaction_intention: InteractionIntention | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_activity_id",
            normalized_identifier(
                self.source_activity_id,
                "source_activity_id",
                maximum_length=128,
            ),
        )
        if self.attention_target is not None:
            object.__setattr__(
                self,
                "attention_target",
                normalized_identifier(
                    self.attention_target,
                    "attention_target",
                ),
            )
        posture = self.posture_tendency
        if isinstance(posture, str):
            posture = BodyPostureTendency(posture)
        if not isinstance(posture, BodyPostureTendency):
            raise TypeError("posture_tendency must be BodyPostureTendency")
        object.__setattr__(self, "posture_tendency", posture)
        for field_name in ("engagement", "movement_energy", "gaze_freedom"):
            object.__setattr__(
                self,
                field_name,
                bounded_number(
                    getattr(self, field_name),
                    field_name,
                    0.0,
                    1.0,
                ),
            )
