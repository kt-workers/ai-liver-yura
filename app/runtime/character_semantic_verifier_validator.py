from __future__ import annotations

import json

from app.adapters.prompt.character_semantic_verifier_prompt_builder import (
    CharacterSemanticVerifierPromptBuilder,
)
from app.domain.activities import Activity
from app.domain.character_response import (
    ResponseContext,
    ResponseValidationResult,
)
from app.domain.character_utterance import CharacterUtterance, LinguisticPerformance
from app.domain.semantic_character_response import SemanticCharacterResponse
from app.domain.semantic_utterance import SemanticUtterancePlan
from app.runtime.character_realization_validator_schema_retry import (
    CharacterRealizationValidator,
)
from app.runtime.character_semantic_verifier import CharacterSemanticVerifier


class CharacterSemanticVerifierValidator(CharacterRealizationValidator):
    """v2 semantic responseでは旧Observer exact reconstructionを使わないValidator。"""

    async def validate(
        self,
        source: Activity,
        context: ResponseContext,
        response: SemanticCharacterResponse,
        *,
        attempt: int = 1,
    ) -> ResponseValidationResult:
        plan = SemanticUtterancePlan.from_context(
            context.memory.get("semantic_utterance_plan")
        )
        if (
            plan is None
            or not self._uses_realization_validation(context, plan)
            or not isinstance(response, SemanticCharacterResponse)
        ):
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
                "character_semantic_verifier:claim_extractor_failed",
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

        structural = self._validate_alignment_contract(plan, response)
        if structural is not None:
            result = ResponseValidationResult(
                accepted=False,
                reason="semantic_v2_alignment_invalid",
                extracted_claims=extracted_claims,
                claim_differences=tuple(structural),
            )
            self._trace_result(source, result)
            return result

        if self._model is None:
            result = ResponseValidationResult(
                False,
                "character_semantic_verifier_model_unavailable",
                extracted_claims=extracted_claims,
            )
            self._trace_result(source, result)
            return result

        utterance = CharacterUtterance(
            speech=response.speech,
            linguistic_performance=(
                response.linguistic_performance
                if response.linguistic_performance is not None
                else LinguisticPerformance()
            ),
            semantic_realizations=response.semantic_realizations,
            realizations=response.semantic_alignment,
        )
        verifier = CharacterSemanticVerifier(
            self._model,  # type: ignore[arg-type]
            CharacterSemanticVerifierPromptBuilder(),
        )
        verifier_result = await verifier.verify(
            source,
            context,
            utterance,
            plan,
            existence_boundaries=self._existence_boundaries(context),
            attempt=attempt,
        )
        decision = verifier_result.decision
        differences = tuple(
            json.dumps(
                item.as_context(),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            for item in decision.differences
        )
        result = ResponseValidationResult(
            accepted=decision.accepted,
            reason=decision.reason,
            extracted_claims=extracted_claims,
            claim_differences=differences,
        )
        self._trace_result(source, result)
        return result

    @staticmethod
    def _validate_alignment_contract(
        plan: SemanticUtterancePlan,
        response: SemanticCharacterResponse,
    ) -> list[str] | None:
        planned = {item.proposition_id: item for item in plan.propositions}
        alignment_ids = [item.proposition_id for item in response.semantic_alignment]
        if len(alignment_ids) != len(set(alignment_ids)):
            return ["semantic_v2:duplicate_alignment"]
        unexpected = sorted(set(alignment_ids) - set(planned))
        if unexpected:
            return [f"semantic_v2:unexpected_alignment:{item}" for item in unexpected]
        if tuple(alignment_ids) != tuple(response.semantic_realizations):
            return ["semantic_v2:alignment_id_mismatch"]
        required = {
            item.proposition_id
            for item in plan.propositions
            if item.realization_policy == "required"
        }
        missing = sorted(required - set(alignment_ids))
        if missing:
            return [f"semantic_v2:required_alignment_missing:{item}" for item in missing]
        return None

    @staticmethod
    def _existence_boundaries(context: ResponseContext) -> tuple[str, ...]:
        envelope = context.constraints.get("_internal_directive")
        if not isinstance(envelope, dict):
            return ()
        raw = envelope.get("existence_boundaries")
        if not isinstance(raw, (list, tuple)):
            return ()
        return tuple(
            item.strip()
            for item in raw
            if isinstance(item, str) and item.strip()
        )
