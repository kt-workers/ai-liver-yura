from __future__ import annotations

import json

from app.adapters.prompt.character_prompt_builder import (
    CharacterPromptBuilder as LegacyCharacterPromptBuilder,
)
from app.adapters.prompt.response_validator_prompt_builder import (
    ResponseValidatorPromptBuilder as LegacyResponseValidatorPromptBuilder,
)
from app.domain.character import CharacterProfile
from app.domain.character_response import CharacterResponse, Claim, ResponseContext


class CharacterPromptBuilder(LegacyCharacterPromptBuilder):
    """Validated Internal Directiveを決定論的にCharacter Promptへ射影する。"""

    def build(
        self,
        context: ResponseContext,
        *,
        character_profile: CharacterProfile | None,
        correction: str | None,
    ) -> str:
        prompt = super().build(
            context,
            character_profile=character_profile,
            correction=correction,
        )
        directive = _validated_directive(context)
        if directive is None:
            return prompt
        return "\n".join(
            [
                prompt,
                "# Validated Internal Directive",
                json.dumps(directive, ensure_ascii=False, default=str),
                "この司令はCoreで検証済みである。Raw User Textから別の意味や方針を"
                "再推定せず、response_modeとresponse_goalを優先する。",
                "question_budgetとnew_direction_budgetは上限として厳守する。"
                "content_requirementsを満たし、forbidden_claimsとexistence_boundariesに"
                "反する主張を生成しない。",
                "character_profileは存在設定を含む確定済みProfileであり、物理的な身体や"
                "現実空間での実体験を根拠なく創作しない。",
            ]
        )


class ResponseValidatorPromptBuilder(LegacyResponseValidatorPromptBuilder):
    """存在境界を含むValidated DirectiveでCharacter Responseを検証する。"""

    def build(
        self,
        context: ResponseContext,
        response: CharacterResponse,
        *,
        extracted_claims: tuple[Claim, ...] = (),
    ) -> str:
        prompt = super().build(
            context,
            response,
            extracted_claims=extracted_claims,
        )
        directive = _validated_directive(context)
        if directive is None:
            return prompt
        return "\n".join(
            [
                prompt,
                "# Validated Internal Directive / Character Profile / Existence Boundaries",
                json.dumps(directive, ensure_ascii=False, default=str),
                "Character Responseがresponse_mode、response_goal、question_budget、"
                "new_direction_budget、content_requirementsに一致するか検証する。",
                "forbidden_claims、character_profile、existence_boundariesのいずれかに"
                "反する身体感覚・実体験・感情断定があればaccepted=falseにする。",
                "engagementの高さだけをjoyやamusementの高さとして扱う表現は、"
                "内部状態への直接質問に対する事実不整合として拒否する。",
                "物理的な身体を持たないProfileで『今はお腹が空いていない』だけを"
                "回答し、人間同様の空腹能力を暗示する表現は拒否する。",
            ]
        )


def _validated_directive(context: ResponseContext) -> dict[str, object] | None:
    value = context.constraints.get("_internal_directive")
    return dict(value) if isinstance(value, dict) else None
