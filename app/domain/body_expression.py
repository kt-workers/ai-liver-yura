from __future__ import annotations

from dataclasses import dataclass

from app.domain.body_value_validation import bounded_number, normalized_identifier


@dataclass(frozen=True, slots=True)
class EmbodiedExpressionIntent:
    """身体部位やモーション名に依存しない高レベル表現意図。"""

    attitude: str = "neutral"
    intensity: float = 0.0
    valence: float = 0.0
    arousal: float = 0.0
    tension: float = 0.0
    openness: float = 0.5
    approach: float = 0.0
    agreement: float = 0.0
    surprise: float = 0.0
    assertiveness: float = 0.0
    warmth: float = 0.5

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "attitude",
            normalized_identifier(
                self.attitude,
                "embodied expression attitude",
            ),
        )
        for field_name in (
            "intensity",
            "arousal",
            "tension",
            "openness",
            "surprise",
            "assertiveness",
            "warmth",
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
        for field_name in ("valence", "approach", "agreement"):
            object.__setattr__(
                self,
                field_name,
                bounded_number(
                    getattr(self, field_name),
                    field_name,
                    -1.0,
                    1.0,
                ),
            )

    def as_payload(self) -> dict[str, float | str]:
        return {
            "attitude": self.attitude,
            "intensity": self.intensity,
            "valence": self.valence,
            "arousal": self.arousal,
            "tension": self.tension,
            "openness": self.openness,
            "approach": self.approach,
            "agreement": self.agreement,
            "surprise": self.surprise,
            "assertiveness": self.assertiveness,
            "warmth": self.warmth,
        }
