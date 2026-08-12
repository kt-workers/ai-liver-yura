from __future__ import annotations

import json
from typing import cast

from app.domain.activities import Activity, ActivityType
from app.domain.character_response import CharacterResponse, ResponseContext
from app.domain.semantic_utterance import SemanticUtterancePlan
from app.domain.semantic_validation import RealizedSemanticObservation
from app.ports.prompt_builder import CharacterRealizationValidationPromptBuilder
from app.runtime.character_realization_validator import (
    CharacterRealizationValidator as _BaseCharacterRealizationValidator,
)
from app.utils.llm_trace import build_llm_trace_context


class CharacterRealizationValidator(_BaseCharacterRealizationValidator):
    """Observerの意味authorityを変えず、schema不正だけを1回再取得する。"""

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
            base_prompt = builder.build_observation(context, response, plan)
        except (AttributeError, TypeError):
            return None

        for contract_attempt in (1, 2):
            prompt = (
                base_prompt
                if contract_attempt == 1
                else self._observer_schema_retry_prompt(base_prompt)
            )
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
                    "observer_contract_attempt": contract_attempt,
                    "semantic_boundary": True,
                },
            )
            try:
                raw = await self._model.validate_character_response(activity)
            except Exception:
                return None

            observations = self._parse_observer_payload(raw)
            if observations is not None:
                trace = build_llm_trace_context(activity)
                self._trace_logger.debug(
                    "character_realization_observer:model_completed",
                    **trace.trace_context.as_log_fields(),
                    llm_role="character_realization_observer",
                    attempt=attempt,
                    observer_contract_attempt=contract_attempt,
                    observation_count=len(observations),
                    semantic_boundary=True,
                )
                return observations

            if contract_attempt == 1:
                trace = build_llm_trace_context(activity)
                self._trace_logger.warning(
                    "character_realization_observer:schema_retry",
                    **trace.trace_context.as_log_fields(),
                    llm_role="character_realization_observer",
                    attempt=attempt,
                    observer_contract_attempt=contract_attempt,
                    semantic_boundary=True,
                )

        return None

    @staticmethod
    def _parse_observer_payload(
        raw: str,
    ) -> tuple[RealizedSemanticObservation, ...] | None:
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
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
        return tuple(observations)

    @staticmethod
    def _observer_schema_retry_prompt(base_prompt: str) -> str:
        return "\n".join(
            (
                base_prompt,
                "# Observer Output Contract Retry",
                "前回出力は意味内容ではなくJSON型契約を満たさなかった。前回の出力値を修正・補完・"
                "正規化せず、同じCharacter Speechをもう一度独立に観測し直す。",
                "Semantic Planの期待state / certainty / concept / intensityを推測して合わせない。",
                "predicate_realizedはJSON booleanのtrueまたはfalseだけを返す。文字列のno/yes/"
                "omitted等で代用しない。",
                "observed_state / observed_certaintyは元の観測規則のclosed enumから選び、"
                "evidence_spansはJSON array[string]として返す。",
                "top-levelは{\"observations\":[...]}または同じtyped observation配列そのものとする。",
                "schemaを満たすために自然言語の意味を有限語彙・regex・substringで推定しない。",
            )
        )
