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
_INTENSITY_STATES = frozenset({"low", "moderate", "high", "very_high"})
# LLM Validatorがsurface markerを見落とした場合の保守的な安全網。
# 固定回答辞書ではなく、発話上で明示的に程度・強弱を付与する語だけを扱う。
_EXPLICIT_INTENSITY_MARKERS = tuple(
    sorted(
        {
            "ほんの少し",
            "少しだけ",
            "ものすごく",
            "めちゃくちゃ",
            "非常に",
            "かなり",
            "とても",
            "すごく",
            "だいぶ",
            "相当",
            "ちょっと",
            "わりと",
            "割と",
            "結構",
            "やや",
            "少し",
        },
        key=len,
        reverse=True,
    )
)


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
        differences = list(
            item.strip()
            for item in differences_value
            if isinstance(item, str) and item.strip()
        ) if isinstance(differences_value, list) else []

        model_accepted = bool(value["accepted"])
        if model_accepted:
            facet_differences = self._accepted_facet_differences(plan, value)
            if facet_differences is None:
                result = ResponseValidationResult(
                    False,
                    "realization_validator_schema_invalid",
                    extracted_claims=extracted_claims,
                )
                self._trace_result(source, result)
                return result
            differences.extend(facet_differences)

        deterministic_surface_differences = self._deterministic_surface_differences(
            plan,
            response.speech,
        )
        for difference in deterministic_surface_differences:
            if difference not in differences:
                differences.append(difference)

        accepted = model_accepted and not differences
        reason = str(value.get("reason") or "semantic_realization_validation")
        if model_accepted and differences:
            reason = "semantic_facet_validation_failed"

        result = ResponseValidationResult(
            accepted=accepted,
            reason=reason,
            extracted_claims=extracted_claims,
            claim_differences=tuple(differences),
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
    def _accepted_facet_differences(
        plan: SemanticUtterancePlan,
        value: dict[str, object],
    ) -> list[str] | None:
        checks = value.get("semantic_checks")
        surface = value.get("surface_evidence")
        if not isinstance(checks, dict) or not isinstance(surface, dict):
            return None

        required_checks = [
            "required_facets_preserved",
            "state_preserved",
            "certainty_preserved",
            "unsupported_intensity_added",
        ]
        if plan.propositions[0].concept is not None:
            required_checks.append("concept_preserved")
        if any(not isinstance(checks.get(name), bool) for name in required_checks):
            return None

        markers_value = surface.get("intensity_markers")
        if not isinstance(markers_value, list) or any(
            not isinstance(item, str) for item in markers_value
        ):
            return None
        intensity_markers = [item.strip() for item in markers_value if item.strip()]

        differences: list[str] = []
        for name in ("required_facets_preserved", "state_preserved", "certainty_preserved"):
            if checks[name] is False:
                differences.append(name)
        if plan.propositions[0].concept is not None and checks["concept_preserved"] is False:
            differences.append("concept_preserved")
        if checks["unsupported_intensity_added"] is True:
            differences.append("unsupported_intensity_added")

        primary_state = plan.propositions[0].state
        if primary_state not in _INTENSITY_STATES and intensity_markers:
            differences.append(
                "unsupported_intensity_markers:" + ",".join(intensity_markers)
            )
        return differences

    @staticmethod
    def _deterministic_surface_differences(
        plan: SemanticUtterancePlan,
        speech: str,
    ) -> list[str]:
        if plan.propositions[0].state in _INTENSITY_STATES:
            return []
        markers = CharacterRealizationValidator._explicit_intensity_markers(speech)
        if not markers:
            return []
        return ["unsupported_intensity_markers:" + ",".join(markers)]

    @staticmethod
    def _explicit_intensity_markers(speech: str) -> list[str]:
        # 長い語から消費し、"ほんの少し"と"少し"のような重複報告を避ける。
        remaining = speech
        found: list[str] = []
        for marker in _EXPLICIT_INTENSITY_MARKERS:
            if marker not in remaining:
                continue
            found.append(marker)
            remaining = remaining.replace(marker, " " * len(marker))
        return found

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
