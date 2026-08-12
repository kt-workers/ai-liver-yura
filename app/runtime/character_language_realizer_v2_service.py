from __future__ import annotations

import json

from app.adapters.prompt.character_language_realizer_v2_prompt_builder import (
    CharacterLanguageRealizerV2PromptBuilder,
)
from app.domain.activities import Activity
from app.domain.character_response import (
    CharacterResponse,
    ResponseClaim,
    ResponseContext,
    VoiceIntent,
)
from app.domain.semantic_character_response import SemanticCharacterResponse
from app.runtime.character_language_realizer_service import CharacterLanguageRealizerService
from app.runtime.character_language_realizer_v2 import CharacterLanguageRealizerV2


class CharacterLanguageRealizerV2Service(CharacterLanguageRealizerService):
    """既存Pipeline互換signatureでv2 Structured Realizerを使用する。"""

    async def generate(
        self,
        source: Activity,
        context: ResponseContext,
        *,
        correction: str | None = None,
        attempt: int = 1,
    ) -> CharacterResponse:
        if not self._uses_language_realizer(context):
            return await super().generate(
                source,
                context,
                correction=correction,
                attempt=attempt,
            )

        realizer = CharacterLanguageRealizerV2(
            self._model,  # type: ignore[arg-type]
            CharacterLanguageRealizerV2PromptBuilder(),
            character_profile=self._character_profile,
        )
        utterance = await realizer.generate_utterance(
            source,
            context,
            correction=self._typed_correction(correction),
            attempt=attempt,
        )
        return SemanticCharacterResponse(
            speech=utterance.speech,
            expression="neutral",
            gesture=None,
            voice_intent=VoiceIntent(),
            pause_after_seconds=0.0,
            claims=(ResponseClaim.CONVERSATION_ONLY,),
            claim_details=(),
            reaction_plan=None,
            linguistic_performance=utterance.linguistic_performance,
            semantic_realizations=utterance.semantic_realizations,
            semantic_alignment=utterance.realizations,
        )

    @staticmethod
    def _typed_correction(correction: str | None) -> dict[str, object] | None:
        if not correction:
            return None
        try:
            payload = json.loads(correction)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        raw_differences = payload.get("claim_differences")
        if not isinstance(raw_differences, list):
            return None

        differences: list[dict[str, object]] = []
        for raw in raw_differences:
            if not isinstance(raw, str):
                continue
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(value, dict):
                continue
            if not {
                "facet",
                "relation",
                "repair",
            }.issubset(value):
                continue
            differences.append(dict(value))
        return {"differences": differences} if differences else None
