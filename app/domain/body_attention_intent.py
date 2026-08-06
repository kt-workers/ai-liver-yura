from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.domain.body_value_validation import bounded_number, normalized_identifier


class BodyAttentionBehavior(str, Enum):
    """Bodyが意味上の注意対象をどう扱うかを表す。"""

    MAINTAIN = "maintain"
    GLANCE = "glance"
    AVOID = "avoid"
    SEARCH = "search"
    WANDER = "wander"


@dataclass(frozen=True, slots=True)
class BodyAttentionIntent:
    """対象選択済みの高レベル注意方針。"""

    target: str
    behavior: BodyAttentionBehavior = BodyAttentionBehavior.MAINTAIN
    engagement: float = 1.0
    avoidance: float = 0.0
    eye_follow: float = 1.0
    head_follow: float = 0.55
    body_follow: float = 0.15

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "target",
            normalized_identifier(self.target, "body attention target"),
        )
        behavior = self.behavior
        if isinstance(behavior, str):
            behavior = BodyAttentionBehavior(behavior)
        if not isinstance(behavior, BodyAttentionBehavior):
            raise TypeError("behavior must be BodyAttentionBehavior")
        object.__setattr__(self, "behavior", behavior)
        for field_name in (
            "engagement",
            "avoidance",
            "eye_follow",
            "head_follow",
            "body_follow",
        ):
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

    def as_payload(self) -> dict[str, float | str]:
        return {
            "target": self.target,
            "behavior": self.behavior.value,
            "engagement": self.engagement,
            "avoidance": self.avoidance,
            "eye_follow": self.eye_follow,
            "head_follow": self.head_follow,
            "body_follow": self.body_follow,
        }
