from __future__ import annotations

import json
from dataclasses import asdict

from app.domain.activities import Activity, ActivityType
from app.domain.character_response import (
    CharacterResponse,
    ResponseContext,
    ResponseValidationResult,
)
from app.domain.semantic_utterance import SemanticUtterancePlan
from app.runtime.character_response_pipeline import ResponseValidator as LegacyResponseValidator
from app.utils.llm_trace import build_llm_trace_context


_INTERNAL_STATE_TYPES = frozenset({"internal_state", "agent_internal_state"})


class CharacterRealizationValidator(LegacyResponseValidator):
    """Semantic Plan適用時は、Character発話が確定意味を保持したかだけを検証する。"""

    async def validate(
        self,
        source: Activity,
        context: ResponseContext,
        response: CharacterResponse,
        *,
        attempt: int = 1,
    ) -> ResponseValidationResult:
        plan = SemanticUtterancePlan.from_context(
            context.memory.get("semantic_utterance_plan")
        )
        if plan is None or not self._uses_realization_validation(context, plan):
            return await super().validate(
                source,
                context,
                response,
                attempt=attempt,
            )

        try:
            extracted_claims = self._claim_extractor.extract(context, response.speech)
        except Exception as error:
            result = ResponseValidationResult(False, "claim_extractor_failed")
            self._trace_logger.warning(
                "character_realization_validator:claim_extractor_failed",
                source_activity_id=source.activity_id,
                error_type=type(error).__name__,
            )
            self._trace_result(source, result)
            return result

        deterministic = self._fact_validator.validate(
            context,
            response,
            extracted_claims,
        )
        if not deterministic.accepted:
            self._trace_result(source, deterministic)
            return deterministic

        required_realization = f"proposition:0:{plan.propositions[0].predicate}"
        if required_realization not in response.semantic_realizations:
            result = ResponseValidationResult(
                accepted=False,
                reason="required_semantic_realization_missing",
                extracted_claims=extracted_claims,
                claim_differences=(required_realization,),
            )
            self._trace_result(source, result)
            return result

        if self._model is None:
            result = ResponseValidationResult(
                accepted=True,
                reason="semantic_realization_structure_valid",
                extracted_claims=extracted_claims,
            )
            self._trace_result(source, result)
            return result

        prompt = self._require_prompt_builder().build(
            context,
            response,
            extracted_claims=extracted_claims,
        )
        activity = Activity(
            activity_type=ActivityType.BEHAVIOR_PLANNING,
            goal="Semantic PlanとCharacter言語実現の意味保持を検証する",
            source_event_id=source.source_event_id,
            context={
                "plugin_prompt_override": prompt,
                "llm_role": "character_realization_validator",
                "trace_context": source.context.get("trace_context"),
                "activity_turn_id": source.context.get("activity_turn_id"),
                "llm_attempt": attempt,
                "semantic_boundary": True,
            },
        )
        try:
            raw = await self._model.validate_character_response(activity)
            value = json.loads(raw)
        except (Exception, json.JSONDecodeError):
            result = ResponseValidationResult(
                False,
                "realization_validator_model_failed",
                extracted_claims=extracted_claims,
            )
            self._trace_result(source, result)
            return result
        if not isinstance(value, dict) or not isinstance(value.get("accepted"), bool):
            result = ResponseValidationResult(
                False,
                "realization_validator_schema_invalid",
                extracted_claims=extracted_claims,
            )
            self._trace_result(source, result)
            return result

        differences_value = value.get("differences", [])
        differences = (
            tuple(
                item.strip()
                for item in differences_value
                if isinstance(item, str) and item.strip()
            )
            if isinstance(differences_value, list)
            else ()
        )
        result = ResponseValidationResult(
            accepted=bool(value["accepted"]),
            reason=str(value.get("reason") or "semantic_realization_validation"),
            extracted_claims=extracted_claims,
            claim_differences=differences,
        )
        trace = build_llm_trace_context(activity)
        self._trace_logger.debug(
            "character_realization_validator:model_completed",
            **trace.trace_context.as_log_fields(),
            llm_role="character_realization_validator",
            attempt=attempt,
            accepted=result.accepted,
            reason=result.reason,
            semantic_boundary=True,
            extracted_claims=[asdict(claim) for claim in extracted_claims],
        )
        self._trace_result(source, result)
        return result

    @staticmethod
    def _uses_realization_validation(
        context: ResponseContext,
        plan: SemanticUtterancePlan,
    ) -> bool:
        semantic_validation = context.memory.get("semantic_validation")
        validated = (
            isinstance(semantic_validation, dict)
            and semantic_validation.get("accepted") is True
        )
        return bool(
            validated
            and plan.target is not None
            and plan.target.type.casefold() in _INTERNAL_STATE_TYPES
            and plan.speech_act == "direct_answer"
            and plan.propositions
        )
