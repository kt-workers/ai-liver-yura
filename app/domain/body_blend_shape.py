from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.domain.body_value_validation import bounded_number, normalized_identifier


class CanonicalBodyBlendShape(str, Enum):
    """初期BodyPoseFrame契約が定義するモデル非依存BlendShape。"""

    EYE_BLINK_LEFT = "eye_blink_left"
    EYE_BLINK_RIGHT = "eye_blink_right"
    JAW_OPEN = "jaw_open"
    MOUTH_SMILE = "mouth_smile"
    MOUTH_FROWN = "mouth_frown"


CANONICAL_BODY_BLEND_SHAPE_NAMES: frozenset[str] = frozenset(
    shape.value for shape in CanonicalBodyBlendShape
)


@dataclass(frozen=True, slots=True)
class BodyBlendShape:
    """顔・目・口のモデル非依存BlendShape値。"""

    name: str
    value: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "name",
            normalized_identifier(
                self.name,
                "blend shape name",
                lowercase=True,
            ),
        )
        object.__setattr__(
            self,
            "value",
            bounded_number(self.value, "value", 0.0, 1.0),
        )

    @property
    def is_canonical(self) -> bool:
        return self.name in CANONICAL_BODY_BLEND_SHAPE_NAMES

    def as_payload(self) -> dict[str, object]:
        return {"name": self.name, "value": self.value}
