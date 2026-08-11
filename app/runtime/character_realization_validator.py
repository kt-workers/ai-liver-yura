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
_STATE_FIDELITY_VALUES = frozenset(
    {
        "exact",
        "weakened",
        "strengthened",
        "polarity_changed",
        "unknown_committed",
        "omitted",
    }
)
_FACET_EVIDENCE_FIELDS = (
    "predicate_evidence_spans",
    "certainty_evidence_spans",
    "concept_evidence_spans",
    "intensity_evidence_spans",
)
_EXPLICIT_INTENSITY_MARKERS = tuple(
    sorted(
        {
            "ほんの少し",
            "ごくわずか",
            "少しだけ",
            "ものすごく",
            "めちゃくちゃ",
            "非常に",
            "かなり",
            "とても",
            "すごく",
            "だいぶ",
            "相当",
            "そこそこ",
            "ほどほど",
            "ちょっと",
            "わりと",
            "割と",
            "結構",
            "控えめ",
            "ほとんど",
            "わずか",
            "低め",
            "弱め",
            "高め",
            "強め",
            "やや",
            "少し",
            "低い",
            "弱い",
            "高い",
            "強い",
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

        deterministic_surface_differences = self._deterministic_surface_differences(
            plan,
            response.speech,
        )
        if self._model is None:
            result = ResponseValidationResult(
                accepted=not deterministic_surface_differences,
                reason=(
                    "semantic_realization_structure_valid"
                    if not deterministic_surface_differences
                    else "semantic_facet_validation_failed"
                ),
                extracted_claims=extracted_claims,
                claim_differences=tuple(deterministic_surface_differences),
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
        assert isinstance(value["accepted"], bool)
        assert isinstance(value["reason"], str)
        assert isinstance(value["differences"], list)

        differences = [item.strip() for item in value["differences"] if item.strip()]
        model_accepted = value["accepted"]
        if model_accepted:
            facet_differences = self._accepted_facet_differences(plan, response, value)
            if facet_differences is None:
                result = ResponseValidationResult(
                    False,
                    "realization_validator_schema_invalid",
                    extracted_claims=extracted_claims,
                )
                self._trace_result(source, result)
                return result
            differences.extend(facet_differences)

        for difference in deterministic_surface_differences:
            if difference not in differences:
                differences.append(difference)

        accepted = model_accepted and not differences
        reason = value["reason"].strip()
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
        if any(not isinstance(item, str) for item in differences):
            return False
        return True

    @staticmethod
    def _accepted_facet_differences(
        plan: SemanticUtterancePlan,
        response: CharacterResponse,
        value: dict[str, object],
    ) -> list[str] | None:
        checks = value.get("semantic_checks")
        surface = value.get("surface_evidence")
        realized_checks = value.get("realized_proposition_checks")
        if (
            not isinstance(checks, dict)
            or not isinstance(surface, dict)
            or not isinstance(realized_checks, list)
        ):
            return None

        required_checks = [
            "required_facets_preserved",
            "predicate_preserved",
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
            not isinstance(item, str) or not item.strip() for item in markers_value
        ):
            return None
        surface_markers = [item.strip() for item in markers_value]

        expected_ids = list(dict.fromkeys(response.semantic_realizations))
        planned_ids = CharacterRealizationValidator._planned_realization_ids(plan)
        if any(realization_id not in planned_ids for realization_id in expected_ids):
            return None
        propositions_by_id = {
            f"proposition:{index}:{proposition.predicate}": proposition
            for index, proposition in enumerate(plan.propositions)
        }

        checks_by_id: dict[str, dict[str, object]] = {}
        evidence_by_id: dict[str, dict[str, list[str]]] = {}
        for item in realized_checks:
            if not isinstance(item, dict):
                return None
            realization_id = item.get("realization_id")
            if not isinstance(realization_id, str) or not realization_id.strip():
                return None
            realization_id = realization_id.strip()
            if realization_id in checks_by_id:
                return None
            if realization_id not in planned_ids:
                return None
            for name in (
                "predicate_preserved",
                "state_preserved",
                "certainty_preserved",
                "concept_preserved",
                "intensity_semantics_preserved",
                "presence_only_counterfactual_equivalent",
            ):
                if not isinstance(item.get(name), bool):
                    return None
            state_fidelity = item.get("state_fidelity")
            if (
                not isinstance(state_fidelity, str)
                or state_fidelity not in _STATE_FIDELITY_VALUES
            ):
                return None

            normalized_evidence: dict[str, list[str]] = {}
            for field_name in _FACET_EVIDENCE_FIELDS:
                evidence_value = item.get(field_name)
                if not isinstance(evidence_value, list) or any(
                    not isinstance(span, str) or not span.strip()
                    for span in evidence_value
                ):
                    return None
                normalized_evidence[field_name] = [
                    span.strip() for span in evidence_value
                ]

            checks_by_id[realization_id] = item
            evidence_by_id[realization_id] = normalized_evidence

        if set(checks_by_id) != set(expected_ids):
            return None

        differences: list[str] = []
        for name in (
            "required_facets_preserved",
            "predicate_preserved",
            "state_preserved",
            "certainty_preserved",
        ):
            if checks[name] is False:
                differences.append(name)
        if plan.propositions[0].concept is not None and checks["concept_preserved"] is False:
            differences.append("concept_preserved")
        if checks["unsupported_intensity_added"] is True:
            differences.append("unsupported_intensity_added")

        for marker in surface_markers:
            if marker not in response.speech:
                differences.append(f"surface_intensity_marker_not_in_speech:{marker}")

        for realization_id in expected_ids:
            item = checks_by_id[realization_id]
            evidence = evidence_by_id[realization_id]
            proposition = propositions_by_id[realization_id]

            for name in (
                "predicate_preserved",
                "state_preserved",
                "certainty_preserved",
                "concept_preserved",
            ):
                if item[name] is False:
                    differences.append(f"{realization_id}:{name}")
            state_fidelity = item["state_fidelity"]
            if state_fidelity != "exact":
                differences.append(f"{realization_id}:state_fidelity:{state_fidelity}")

            predicate_spans = evidence["predicate_evidence_spans"]
            certainty_spans = evidence["certainty_evidence_spans"]
            concept_spans = evidence["concept_evidence_spans"]
            intensity_spans = evidence["intensity_evidence_spans"]

            if item["predicate_preserved"] is True and not predicate_spans:
                differences.append(f"{realization_id}:predicate_evidence_missing")
            CharacterRealizationValidator._append_spans_not_in_speech(
                differences,
                realization_id,
                "predicate",
                predicate_spans,
                response.speech,
            )

            if (
                proposition.certainty in {"medium", "low"}
                and item["certainty_preserved"] is True
                and not certainty_spans
            ):
                differences.append(f"{realization_id}:certainty_evidence_missing")
            CharacterRealizationValidator._append_spans_not_in_speech(
                differences,
                realization_id,
                "certainty",
                certainty_spans,
                response.speech,
            )

            if proposition.concept is not None:
                if item["concept_preserved"] is True and not concept_spans:
                    differences.append(f"{realization_id}:concept_evidence_missing")
            elif concept_spans:
                differences.append(f"{realization_id}:unexpected_concept_evidence")
            CharacterRealizationValidator._append_spans_not_in_speech(
                differences,
                realization_id,
                "concept",
                concept_spans,
                response.speech,
            )

            if proposition.state in _INTENSITY_STATES:
                if item["intensity_semantics_preserved"] is False:
                    differences.append(
                        f"{realization_id}:intensity_semantics_preserved"
                    )
                if item["presence_only_counterfactual_equivalent"] is True:
                    differences.append(
                        f"{realization_id}:presence_only_counterfactual_equivalent"
                    )
                if not intensity_spans:
                    differences.append(f"{realization_id}:intensity_evidence_missing")
                CharacterRealizationValidator._append_spans_not_in_speech(
                    differences,
                    realization_id,
                    "intensity",
                    intensity_spans,
                    response.speech,
                )
                if intensity_spans and not CharacterRealizationValidator._has_explicit_degree_evidence(
                    intensity_spans
                ):
                    differences.append(
                        f"{realization_id}:intensity_evidence_not_explicit_degree"
                    )
            else:
                if item["intensity_semantics_preserved"] is not True:
                    differences.append(
                        f"{realization_id}:non_intensity_semantics_flag_invalid"
                    )
                if item["presence_only_counterfactual_equivalent"] is not False:
                    differences.append(
                        f"{realization_id}:non_intensity_counterfactual_flag_invalid"
                    )
                if intensity_spans:
                    differences.append(
                        f"{realization_id}:unexpected_intensity_evidence"
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
    def _has_explicit_degree_evidence(spans: list[str]) -> bool:
        return any(
            CharacterRealizationValidator._explicit_intensity_markers(span)
            for span in spans
        )

    @staticmethod
    def _deterministic_surface_differences(
        plan: SemanticUtterancePlan,
        speech: str,
    ) -> list[str]:
        if CharacterRealizationValidator._plan_has_intensity_state(plan):
            return []
        markers = CharacterRealizationValidator._explicit_intensity_markers(speech)
        if not markers:
            return []
        return ["unsupported_intensity_markers:" + ",".join(markers)]

    @staticmethod
    def _planned_realization_ids(plan: SemanticUtterancePlan) -> set[str]:
        return {
            f"proposition:{index}:{proposition.predicate}"
            for index, proposition in enumerate(plan.propositions)
        }

    @staticmethod
    def _plan_has_intensity_state(plan: SemanticUtterancePlan) -> bool:
        return any(proposition.state in _INTENSITY_STATES for proposition in plan.propositions)

    @staticmethod
    def _explicit_intensity_markers(speech: str) -> list[str]:
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
