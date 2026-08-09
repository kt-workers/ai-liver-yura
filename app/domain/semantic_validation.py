from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SemanticPlanValidationResult:
    """Character生成前のSemanticUtterancePlan検証結果。"""

    accepted: bool
    reason: str
    differences: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("Semantic validation reasonは空にできません。")
        if any(not item.strip() for item in self.differences):
            raise ValueError("Semantic validation differencesに空文字は使用できません。")

    def as_context(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "reason": self.reason,
            "differences": list(self.differences),
        }
