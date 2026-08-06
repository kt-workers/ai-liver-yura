from __future__ import annotations

from dataclasses import dataclass

from app.domain.body_value_validation import bounded_number, normalized_identifier


@dataclass(frozen=True, slots=True)
class BodyAttentionCandidate:
    """PerceptionからBodyへ渡す注視候補。

    x／yは正規化画面空間であり、候補選択ロジックはこのDTOに持たせない。
    """

    candidate_id: str
    x: float
    y: float
    salience: float = 0.5
    novelty: float = 0.0
    threat: float = 0.0
    relevance: float = 0.5
    stability: float = 0.7

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_id",
            normalized_identifier(self.candidate_id, "candidate_id"),
        )
        object.__setattr__(self, "x", bounded_number(self.x, "x", -1.0, 1.0))
        object.__setattr__(self, "y", bounded_number(self.y, "y", -1.0, 1.0))
        for name in ("salience", "novelty", "threat", "relevance", "stability"):
            object.__setattr__(
                self,
                name,
                bounded_number(getattr(self, name), name, 0.0, 1.0),
            )

    def as_payload(self) -> dict[str, float | str]:
        return {
            "candidate_id": self.candidate_id,
            "x": self.x,
            "y": self.y,
            "salience": self.salience,
            "novelty": self.novelty,
            "threat": self.threat,
            "relevance": self.relevance,
            "stability": self.stability,
        }
