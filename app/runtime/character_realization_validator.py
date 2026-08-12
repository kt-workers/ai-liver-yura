from __future__ import annotations

import json
from dataclasses import asdict
from typing import cast

from app.domain.activities import Activity, ActivityType
from app.domain.character_response import (
    CharacterResponse,
    ResponseContext,
    ResponseValidationResult,
)
from app.domain.semantic_utterance import SemanticUtterancePlan
from app.domain.semantic_validation import RealizedSemanticObservation
from app.ports.prompt_builder import CharacterRealizationValidationPromptBuilder
from app.runtime.character_response_pipeline import ResponseValidator as LegacyResponseValidator
from app.utils.llm_trace import build_llm_trace_context


_INTERNAL_STATE_TYPES = frozenset({"internal_state", "agent_internal_state"})
_POST_OBSERVATION_CHECKS = (
    "required_content_preserved",
    "forbidden_additions_absent",
    "unsupported_new_fact_absent",
    "existence_boundary_preserved",
    "budget_preserved",
)


class CharacterRealizationValidator(LegacyResponseValidator):
    """Semantic Plan適用時に意味保持をObserverと後段契約へ分離して検証する。"""

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
            return await super().validate(source, context, response, attempt=attempt)

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

        planned_realization_ids = self._planned_realization_ids(plan)
        unplanned_realizations = [
            realization_id
            for realization_id in response.semantic_realizations
            if realization_id not in planned_realization_ids
        ]
        if unplanned_realizations:
            result = ResponseValidationResult(
                accepted=False,
                reason="unknown_semantic_realization",
                extracted_claims=extracted_claims,
                claim_differences=tuple(unplanned_realizations),
            )
            self._trace_result(source, result)
            return result

        if self._model is None:
            result = ResponseValidationResult(
                accepted=False,
                reason="realization_validator_model_unavailable",
                extracted_claims=extracted_claims,
            )
            self._trace_result(source, result)
            return result

        observations = await self._observe_realized_semantics(
            source,
            context,
            response,
            plan,
            attempt=attempt,
        )
        if observations is None:
            result = ResponseValidationResult(
                accepted=False,
                reason="realization_observer_schema_invalid",
                extracted_claims=extracted_claims,
            )
            self._trace_result(source, result)
            return result

        observation_differences = self._observation_differences(
            plan,
            response,
            observations,
        )
        if observation_differences:
            result = ResponseValidationResult(
                accepted=False,
                reason=self._observation_failure_reason(observation_differences),
                extracted_claims=extracted_claims,
                claim_differences=tuple(observation_differences),
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
            goal="Observer後のCharacter意味境界を検証する",
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
        except Exception:
            result = ResponseValidationResult(
                False,
                "realization_validator_model_failed",
                extracted_claims=extracted_claims,
            )
            self._trace_result(source, result)
            return result

        if not self._valid_top_level_schema(value):
            result = ResponseValidationResult(
                False,
                "realization_validator_schema_invalid",
                extracted_claims=extracted_claims,
            )
            self._trace_result(source, result)
            return result

        assert isinstance(value, dict)
        contract_differences = self._accepted_post_observation_differences(
            plan,
            response,
            value,
        )
        if contract_differences is None:
            result = ResponseValidationResult(
                False,
                "realization_validator_schema_invalid",
                extracted_claims=extracted_claims,
            )
            self._trace_result(source, result)
            return result

        accepted = not contract_differences
        reason = (
            "post_observation_semantic_contract_consistent"
            if accepted
            else "post_observation_semantic_contract_failed"
        )
        result = ResponseValidationResult(
            accepted=accepted,
            reason=reason,
            extracted_claims=extracted_claims,
            claim_differences=tuple(contract_differences),
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

    async def _observe_realized_semantics(
        self,
        source: Activity,
        context: ResponseContext,
        response: CharacterResponse,
        plan: SemanticUtterancePlan,
        *,
        attempt: int,
    ) -> tuple[RealizedSemanticObservation, ...] | None:
        builder = cast(
            CharacterRealizationValidationPromptBuilder,
            self._require_prompt_builder(),
        )
        try:
            prompt = builder.build_observation(context, response, plan)
        except (AttributeError, TypeError):
            return None

        activity = Activity(
            activity_type=ActivityType.BEHAVIOR_PLANNING,
            goal="Character発話が実際に表した意味を期待値なしで観測する",
            source_event_id=source.source_event_id,
            context={
                "plugin_prompt_override": prompt,
                "llm_role": "character_realization_observer",
                "trace_context": source.context.get("trace_context"),
                "activity_turn_id": source.context.get("activity_turn_id"),
                "llm_attempt": attempt,
                "semantic_boundary": True,
            },
        )
        try:
            raw = await self._model.validate_character_response(activity)
            value = json.loads(raw)
        except Exception:
            return None
        if isinstance(value, list):
            raw_observations = value
        elif isinstance(value, dict):
            raw_observations = value.get("observations")
        else:
            return None
        if not isinstance(raw_observations, list):
            return None

        observations: list[RealizedSemanticObservation] = []
        for raw_observation in raw_observations:
            observation = RealizedSemanticObservation.from_mapping(raw_observation)
            if observation is None:
                return None
            observations.append(observation)

        trace = build_llm_trace_context(activity)
        self._trace_logger.debug(
            "character_realization_observer:model_completed",
            **trace.trace_context.as_log_fields(),
            llm_role="character_realization_observer",
            attempt=attempt,
            observation_count=len(observations),
            semantic_boundary=True,
        )
        return tuple(observations)

    @staticmethod
    def _observation_failure_reason(differences: list[str]) -> str:
        if any(":observed_state_mismatch:" in item for item in differences):
            return "observed_semantic_state_fidelity_mismatch"
        if any(":observed_certainty_mismatch:" in item for item in differences):
            return "observed_semantic_certainty_mismatch"
        return "observed_semantic_state_mismatch"

    @staticmethod
    def _observation_differences(
        plan: SemanticUtterancePlan,
        response: CharacterResponse,
        observations: tuple[RealizedSemanticObservation, ...],
    ) -> list[str]:
        expected_ids = list(dict.fromkeys(response.semantic_realizations))
        by_id: dict[str, RealizedSemanticObservation] = {}
        for observation in observations:
            if observation.realization_id in by_id:
                return [f"duplicate_observation:{observation.realization_id}"]
            by_id[observation.realization_id] = observation

        if set(by_id) != set(expected_ids):
            missing = sorted(set(expected_ids) - set(by_id))
            extra = sorted(set(by_id) - set(expected_ids))
            return [
                *(f"observation_missing:{item}" for item in missing),
                *(f"unexpected_observation:{item}" for item in extra),
            ]

        planned_by_id = {
            f"proposition:{index}:{proposition.predicate}": proposition
            for index, proposition in enumerate(plan.propositions)
        }
        differences: list[str] = []
        for realization_id in expected_ids:
            observation = by_id[realization_id]
            proposition = planned_by_id[realization_id]
            if not observation.predicate_realized:
                differences.append(f"{realization_id}:predicate_not_observed")
            if observation.observed_state != proposition.state:
                differences.append(
                    f"{realization_id}:observed_state_mismatch:"
                    f"expected={proposition.state}:observed={observation.observed_state}"
                )
            if observation.observed_certainty != proposition.certainty:
                differences.append(
                    f"{realization_id}:observed_certainty_mismatch:"
                    f"expected={proposition.certainty}:observed={observation.observed_certainty}"
                )
            if observation.predicate_realized and not observation.predicate_evidence_spans:
                differences.append(f"{realization_id}:observer_predicate_evidence_missing")
            if observation.observed_state != "omitted" and not observation.state_evidence_spans:
                differences.append(f"{realization_id}:observer_state_evidence_missing")
            if (
                observation.observed_certainty in {"medium", "low"}
                and not observation.certainty_evidence_spans
            ):
                differences.append(f"{realization_id}:observer_certainty_evidence_missing")
            for facet, spans in (
                ("predicate", observation.predicate_evidence_spans),
                ("state", observation.state_evidence_spans),
                ("certainty", observation.certainty_evidence_spans),
            ):
                for span in spans:
                    if span not in response.speech:
                        differences.append(
                            f"{realization_id}:observer_{facet}_evidence_not_in_speech:{span}"
                        )
        return differences

    @staticmethod
    def _valid_top_level_schema(value: object) -> bool:
        if not isinstance(value, dict):
            return False
        if not isinstance(value.get("accepted"), bool):
            return False
        reason = value.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            return False
        differences = value.get("differences")
        if not isinstance(differences, list):
            return False
        return not any(not isinstance(item, str) for item in differences)

    @staticmethod
    def _accepted_post_observation_differences(
        plan: SemanticUtterancePlan,
        response: CharacterResponse,
        value: dict[str, object],
    ) -> list[str] | None:
        checks = value.get("semantic_checks")
        realized_checks = value.get("realized_proposition_checks")
        if not isinstance(checks, dict) or not isinstance(realized_checks, list):
            return None
        if any(not isinstance(checks.get(name), bool) for name in _POST_OBSERVATION_CHECKS):
            return None

        expected_ids = list(dict.fromkeys(response.semantic_realizations))
        planned_ids = CharacterRealizationValidator._planned_realization_ids(plan)
        if any(realization_id not in planned_ids for realization_id in expected_ids):
            return None
        propositions_by_id = {
            f"proposition:{index}:{proposition.predicate}": proposition
            for index, proposition in enumerate(plan.propositions)
        }

        checks_by_id: dict[str, dict[str, object]] = {}
        evidence_by_id: dict[str, tuple[list[str], list[str]]] = {}
        for item in realized_checks:
            if not isinstance(item, dict):
                return None
            realization_id = item.get("realization_id")
            predicate_preserved = item.get("predicate_preserved")
            concept_preserved = item.get("concept_preserved")
            predicate_evidence = item.get("predicate_evidence_spans")
            concept_evidence = item.get("concept_evidence_spans")
            if (
                not isinstance(realization_id, str)
                or not realization_id.strip()
                or not isinstance(predicate_preserved, bool)
                or not isinstance(concept_preserved, bool)
                or not isinstance(predicate_evidence, list)
                or not isinstance(concept_evidence, list)
                or any(
                    not isinstance(span, str) or not span.strip()
                    for span in (*predicate_evidence, *concept_evidence)
                )
            ):
                return None
            realization_id = realization_id.strip()
            if realization_id in checks_by_id or realization_id not in planned_ids:
                return None
            checks_by_id[realization_id] = item
            evidence_by_id[realization_id] = (
                [span.strip() for span in predicate_evidence],
                [span.strip() for span in concept_evidence],
            )

        if set(checks_by_id) != set(expected_ids):
            return None

        differences: list[str] = []
        for name in _POST_OBSERVATION_CHECKS:
            if checks[name] is False:
                differences.append(name)

        for realization_id in expected_ids:
            item = checks_by_id[realization_id]
            proposition = propositions_by_id[realization_id]
            predicate_spans, concept_spans = evidence_by_id[realization_id]

            if item["predicate_preserved"] is False:
                differences.append(f"{realization_id}:predicate_preserved")
            elif not predicate_spans:
                differences.append(f"{realization_id}:predicate_evidence_missing")
            CharacterRealizationValidator._append_spans_not_in_speech(
                differences,
                realization_id,
                "predicate",
                predicate_spans,
                response.speech,
            )

            if proposition.concept is not None:
                if item["concept_preserved"] is False:
                    differences.append(f"{realization_id}:concept_preserved")
                elif not concept_spans:
                    differences.append(f"{realization_id}:concept_evidence_missing")
                CharacterRealizationValidator._append_spans_not_in_speech(
                    differences,
                    realization_id,
                    "concept",
                    concept_spans,
                    response.speech,
                )

        return differences

    @staticmethod
    def _append_spans_not_in_speech(
        differences: list[str],
        realization_id: str,
        facet: str,
        spans: list[str],
        speech: str,
    ) -> None:
        for span in spans:
            if span not in speech:
                differences.append(
                    f"{realization_id}:{facet}_evidence_not_in_speech:{span}"
                )

    @staticmethod
    def _planned_realization_ids(plan: SemanticUtterancePlan) -> set[str]:
        return {
            f"proposition:{index}:{proposition.predicate}"
            for index, proposition in enumerate(plan.propositions)
        }

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