from __future__ import annotations

import json

from app.domain.character_response import CharacterResponse, ResponseClaim, VoiceIntent
from app.domain.character_utterance import CharacterUtterance
from app.runtime.avatar_performance_character_service import (
    AvatarPerformanceCharacterLlmService,
)


class CharacterLanguageRealizerService(AvatarPerformanceCharacterLlmService):
    """新CharacterUtterance Schemaを既存CharacterResponse Pipelineへ接続する移行Adapter。"""

    @staticmethod
    def parse(raw: str) -> CharacterResponse | None:
        try:
            value = json.loads(raw.strip())
        except json.JSONDecodeError:
            return AvatarPerformanceCharacterLlmService.parse(raw)

        utterance = CharacterUtterance.from_context(value)
        if utterance is None:
            return AvatarPerformanceCharacterLlmService.parse(raw)

        # #227ではCharacter LLMは言語表現だけを所有する。
        # expression / voice / acoustic pauseは下流責務へ移行するため、
        # 既存Pipeline互換値はAdapter側のneutral defaultとして補う。
        return CharacterResponse(
            speech=utterance.speech,
            expression="neutral",
            gesture=None,
            voice_intent=VoiceIntent(),
            pause_after_seconds=0.0,
            claims=(ResponseClaim.CONVERSATION_ONLY,),
            claim_details=(),
            reaction_plan=None,
        )
