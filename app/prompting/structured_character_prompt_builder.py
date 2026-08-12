from __future__ import annotations

import json
from dataclasses import asdict
from typing import Mapping

from app.domain.character import CharacterProfile
from app.domain.semantic_utterance_v2 import SemanticUtterancePlanV2


class StructuredCharacterPromptBuilder:
    """Semantic Plan v2を自然なCharacter speechへ実現する短いPromptを構築する。"""

    USER_WORDING_HINT_LIMIT = 500

    def build(
        self,
        *,
        character_profile: CharacterProfile | None,
        plan: SemanticUtterancePlanV2,
        user_wording_hint: str = "",
        regeneration_differences: Mapping[str, object] | None = None,
    ) -> str:
        hint = self._bounded_hint(user_wording_hint)
        lines = [
            "Role: Character Language Realizer",
            "",
            "Input:",
            "Character Profile: "
            + json.dumps(
                asdict(character_profile) if character_profile is not None else {},
                ensure_ascii=False,
                default=str,
                separators=(",", ":"),
            ),
            "Normalized Semantic Plan v2: "
            + json.dumps(
                plan.as_context(),
                ensure_ascii=False,
                default=str,
                separators=(",", ":"),
            ),
            "Bounded User Wording Hint: "
            + json.dumps(hint, ensure_ascii=False, separators=(",", ":")),
        ]
        if regeneration_differences:
            lines.append(
                "Typed Regeneration Differences: "
                + json.dumps(
                    dict(regeneration_differences),
                    ensure_ascii=False,
                    default=str,
                    separators=(",", ":"),
                )
            )
        lines.extend(
            [
                "",
                "Rules:",
                "1. Planの事実を変更しない。",
                "2. required propositionは必ず自然なspeechへ表現する。",
                "3. optional propositionは完全に表現できる場合だけ使い、不要なら省略する。",
                "4. 各propositionの非null facetを保つ。",
                "5. certaintyはepistemic commitment、degreeはintensity。両者を混同しない。",
                "6. Planにない自己状態・事実を追加しない。",
                "7. Character Profileは言い方だけに使う。",
                "8. realizationsは意味判定結果ではなく、speech内で各propositionを表現した箇所の追跡hintだけを返す。",
                "9. evidence_spansにはspeechに実在する短いsubstringだけを入れる。",
            ]
        )
        return "\n".join(lines)

    @classmethod
    def _bounded_hint(cls, value: str) -> str:
        if not isinstance(value, str):
            return ""
        normalized = value.strip()
        if len(normalized) <= cls.USER_WORDING_HINT_LIMIT:
            return normalized
        return normalized[: cls.USER_WORDING_HINT_LIMIT]
