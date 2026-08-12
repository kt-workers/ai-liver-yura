from __future__ import annotations

from app.domain.activities import Activity
from app.domain.character import CharacterProfile
from app.domain.character_response import ResponseContext
from app.domain.character_utterance import CharacterUtterance
from app.domain.semantic_utterance import SemanticUtterancePlan
from app.ports.llm_roles import StructuredCharacterModel
from app.ports.structured_output import (
    StructuredOutputGenerationError,
    StructuredOutputUnsupportedError,
)
from app.runtime.semantic_realization_v2_contracts import character_utterance_v2_contract


class CharacterLanguageRealizerV2:
    """確定済みv2 Semantic PlanをStructured Outputで自然文へ言語実現する。"""

    def __init__(
        self,
        model: StructuredCharacterModel,
        prompt_builder: object,
        *,
        character_profile: CharacterProfile | None = None,
        reasoning_effort: str = "none",
    ) -> None:
        self._model = model
        self._prompt_builder = prompt_builder
        self._character_profile = character_profile
        self._reasoning_effort = reasoning_effort

    async def generate_utterance(
        self,
        source: Activity,
        context: ResponseContext,
        *,
        correction: dict[str, object] | None = None,
        attempt: int = 1,
    ) -> CharacterUtterance:
        plan = SemanticUtterancePlan.from_context(
            context.memory.get("semantic_utterance_plan")
        )
        if plan is None or not plan.propositions:
            raise ValueError("Character Language Realizer v2にはSemanticUtterancePlanが必要です。")
        build = getattr(self._prompt_builder, "build", None)
        if not callable(build):
            raise TypeError("Character Language Realizer v2 prompt builderが不正です。")
        prompt = build(
            context,
            character_profile=self._character_profile,
            correction=correction,
        )
        activity = Activity(
            activity_type=source.activity_type,
            goal="確定済みSemantic Plan v2をCharacter Profileに沿って言語実現する",
            source_event_id=source.source_event_id,
            context={
                "plugin_prompt_override": prompt,
                "llm_role": "character_language_realizer_v2",
                "reasoning_effort": self._reasoning_effort,
                "event_id": source.context.get("event_id"),
                "trace_context": source.context.get("trace_context"),
                "activity_turn_id": source.context.get("activity_turn_id"),
                "llm_attempt": attempt,
                "semantic_boundary": True,
            },
        )
        try:
            payload = await self._model.generate_structured_character_response(
                activity,
                character_utterance_v2_contract(),
            )
        except (StructuredOutputUnsupportedError, StructuredOutputGenerationError):
            raise
        except Exception as error:
            raise StructuredOutputGenerationError(
                "Character Language Realizer v2 model failed"
            ) from error

        utterance = CharacterUtterance.from_context(payload)
        if utterance is None:
            raise StructuredOutputGenerationError(
                "Character Language Realizer v2 returned an invalid domain payload"
            )
        self._validate_alignment(plan, utterance)
        return utterance

    @staticmethod
    def _validate_alignment(
        plan: SemanticUtterancePlan,
        utterance: CharacterUtterance,
    ) -> None:
        planned = {item.proposition_id: item for item in plan.propositions}
        alignment_ids = {item.proposition_id for item in utterance.realizations}
        unexpected = alignment_ids - set(planned)
        if unexpected:
            raise StructuredOutputGenerationError(
                "Character Language Realizer v2 returned an unplanned proposition_id"
            )
        required = {
            item.proposition_id
            for item in plan.propositions
            if item.realization_policy == "required"
        }
        if not required.issubset(alignment_ids):
            raise StructuredOutputGenerationError(
                "Character Language Realizer v2 omitted a required proposition alignment"
            )
        for alignment in utterance.realizations:
            if not alignment.evidence_spans:
                raise StructuredOutputGenerationError(
                    "Character Language Realizer v2 alignment requires evidence_spans"
                )
