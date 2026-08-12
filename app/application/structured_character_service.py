from __future__ import annotations

from dataclasses import replace
from typing import Mapping

from app.contracts.character_utterance_v2_schema import (
    CHARACTER_UTTERANCE_V2_CONTRACT,
)
from app.domain.activities import Activity
from app.domain.character import CharacterProfile
from app.domain.character_utterance_v2 import CharacterUtteranceV2
from app.domain.semantic_utterance_v2 import SemanticUtterancePlanV2
from app.ports.structured_output import StructuredCharacterModel
from app.prompting.structured_character_prompt_builder import (
    StructuredCharacterPromptBuilder,
)


class CharacterStructuredOutputError(RuntimeError):
    """Character structured outputをtyped utteranceとして採用できない。"""


class StructuredCharacterService:
    """Semantic Plan v2をCharacter speechへ変換し、構造整合だけを確認する。"""

    def __init__(
        self,
        model: StructuredCharacterModel,
        *,
        character_profile: CharacterProfile | None,
        prompt_builder: StructuredCharacterPromptBuilder | None = None,
    ) -> None:
        self._model = model
        self._character_profile = character_profile
        self._prompt_builder = prompt_builder or StructuredCharacterPromptBuilder()

    async def generate(
        self,
        source: Activity,
        plan: SemanticUtterancePlanV2,
        *,
        user_wording_hint: str = "",
        regeneration_differences: Mapping[str, object] | None = None,
    ) -> CharacterUtteranceV2:
        prompt = self._prompt_builder.build(
            character_profile=self._character_profile,
            plan=plan,
            user_wording_hint=user_wording_hint,
            regeneration_differences=regeneration_differences,
        )
        context = dict(source.context)
        context.update(
            {
                "llm_role": "character_language_realizer_v2",
                "plugin_prompt_override": prompt,
                "semantic_utterance_plan_v2": plan.as_context(),
            }
        )
        request = replace(source, context=context)

        payload = await self._model.generate_character_utterance(
            request,
            CHARACTER_UTTERANCE_V2_CONTRACT,
        )
        utterance = CharacterUtteranceV2.from_context(payload)
        if utterance is None:
            raise CharacterStructuredOutputError(
                "Character structured outputがCharacterUtteranceV2契約に一致しません。"
            )
        try:
            utterance.validate_plan_alignment(plan)
        except ValueError as error:
            raise CharacterStructuredOutputError(str(error)) from error
        return utterance
