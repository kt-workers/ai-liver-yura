from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.contracts.common import require_aware, require_identifier

MAX_PRIOR_REALIZATIONS = 3


@dataclass(frozen=True, slots=True)
class CharacterLanguagePriorConstraintRevision:
    constraint_id: str
    source_revision: int

    def __post_init__(self) -> None:
        require_identifier(self.constraint_id, "constraint_id")
        if type(self.source_revision) is not int or self.source_revision < 0:
            raise ValueError("source_revision は0以上の整数でなければなりません")


@dataclass(frozen=True, slots=True)
class CharacterLanguagePriorRealizationView:
    source_utterance_id: str
    semantic_plan_id: str
    character_id: str
    character_schema_version: int
    character_definition_revision: int
    constraint_revisions: tuple[CharacterLanguagePriorConstraintRevision, ...]
    text: str
    committed_at: datetime

    def __post_init__(self) -> None:
        for name in ("source_utterance_id", "semantic_plan_id", "character_id", "text"):
            require_identifier(getattr(self, name), name)
        for name in ("character_schema_version", "character_definition_revision"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} は0以上の整数でなければなりません")
        if not isinstance(self.constraint_revisions, (tuple, list)):
            raise ValueError("constraint_revisions は配列でなければなりません")
        revisions = tuple(self.constraint_revisions)
        if any(
            not isinstance(item, CharacterLanguagePriorConstraintRevision)
            for item in revisions
        ):
            raise ValueError("constraint_revisions に不正な値があります")
        if len({item.constraint_id for item in revisions}) != len(revisions):
            raise ValueError("prior constraint_id は重複できません")
        object.__setattr__(self, "constraint_revisions", revisions)
        require_aware(self.committed_at, "committed_at")

    def to_prompt_dict(self) -> dict[str, object]:
        """Authority照合済みpriorからstyle-only viewだけをProviderへ投影する。"""

        return {
            "source_utterance_id": self.source_utterance_id,
            "text": self.text,
            "committed_at": self.committed_at.isoformat(),
        }


__all__ = [
    "MAX_PRIOR_REALIZATIONS",
    "CharacterLanguagePriorConstraintRevision",
    "CharacterLanguagePriorRealizationView",
]
