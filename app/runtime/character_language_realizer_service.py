from __future__ import annotations

import json

from app.domain.activities import Activity
from app.domain.character_response import (
    CharacterResponse,
    ResponseClaim,
    ResponseContext,
    VoiceIntent,
)
from app.domain.character_utterance import CharacterUtterance
from app.domain.semantic_utterance import SemanticUtterancePlan
from app.runtime.avatar_performance_character_service import (
    AvatarPerformanceCharacterLlmService,
)
from app.utils.llm_trace import build_llm_trace_context


_INTERNAL_STATE_TYPES = frozenset({"internal_state", "agent_internal_state"})


class CharacterLanguageRealizerService(AvatarPerformanceCharacterLlmService):
    """Character LLMを言語実現専用境界へ接続し、既存Pipelineへ互換変換する。"""

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

        prompt = self._prompt_builder.build(
            context,
            character_profile=self._character_profile,
            correction=correction,
        )
        # 新Language Realizer経路ではPrompt外のActivity Contextからraw stateを参照できないよう、
        # Model invocationへuser_input/full ResponseContext/Emotion/Drive/Activity payloadを渡さない。
        activity = Activity(
            activity_type=source.activity_type,
            goal="確定済み発言意味をCharacter Profileに沿って言語実現する",
            source_event_id=source.source_event_id,
            context={
                "plugin_prompt_override": prompt,
                "llm_role": "character_language_realizer",
                "event_id": source.context.get("event_id"),
                "trace_context": source.context.get("trace_context"),
                "activity_turn_id": source.context.get("activity_turn_id"),
                "llm_attempt": attempt,
                "semantic_boundary": True,
            },
        )
        raw = await self._model.generate_character_response(activity)
        response = self.parse(raw)
        if response is None:
            raise ValueError("Character Language Realizerの構造化応答が不正です。")
        trace = build_llm_trace_context(activity)
        self._trace_logger.info(
            "character_language_realizer:response_generated",
            **trace.trace_context.as_log_fields(),
            llm_role="character_language_realizer",
            request_id=trace.request_id,
            attempt=attempt,
            source_activity_id=source.activity_id,
            speech_length=len(response.speech),
            semantic_boundary=True,
        )
        return response

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

    @staticmethod
    def _uses_language_realizer(context: ResponseContext) -> bool:
        plan = SemanticUtterancePlan.from_context(
            context.memory.get("semantic_utterance_plan")
        )
        return bool(
            plan is not None
            and plan.target is not None
            and plan.target.type.casefold() in _INTERNAL_STATE_TYPES
            and plan.speech_act == "direct_answer"
            and plan.propositions
        )
