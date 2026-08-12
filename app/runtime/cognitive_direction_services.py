from __future__ import annotations

from app.domain.activities import Activity, ActivityType
from app.domain.cognitive_direction import (
    InternalDirective,
    StructuredInputMeaning,
)
from app.ports.cognitive_direction import (
    InputMeaningModel,
    InputMeaningPromptBuilder,
    InternalDirectiveModel,
    InternalDirectivePromptBuilder,
)
from app.runtime.cognitive_direction_parsers import (
    InputMeaningJsonParser,
    InternalDirectiveJsonParser,
)
from app.runtime.interaction_intention_shadow_observer import (
    InteractionIntentionShadowObserver,
    InternalDirectivePlanningObservation,
)
from app.runtime.internal_directive_candidate_normalizer import (
    InternalDirectiveCandidateNormalizer,
)


class InputMeaningInterpreter:
    def __init__(
        self,
        model: InputMeaningModel,
        *,
        prompt_builder: InputMeaningPromptBuilder,
        parser: InputMeaningJsonParser | None = None,
    ) -> None:
        self._model = model
        self._prompt_builder = prompt_builder
        self._parser = parser or InputMeaningJsonParser()

    async def interpret(
        self,
        activity: Activity,
        planning_input: dict[str, object],
    ) -> StructuredInputMeaning | None:
        event = planning_input.get("event")
        event_data = event if isinstance(event, dict) else {}
        source_text = str(event_data.get("user_text") or "")
        prompt = self._prompt_builder.build(planning_input)
        request = Activity(
            activity_type=ActivityType.BEHAVIOR_PLANNING,
            goal="ObservedInputをStructuredInputMeaningへ変換する",
            context={
                "plugin_prompt_override": prompt,
                "llm_role": "input_meaning_interpreter",
                "event_id": activity.context.get("event_id"),
                "trace_context": activity.context.get("trace_context"),
                "constraints": [
                    "入力側の意味だけを解析する",
                    "Activityや応答方針を決めない",
                ],
            },
            source_event_id=activity.source_event_id,
        )
        try:
            raw = await self._model.interpret_input_meaning(request)
        except Exception:
            return None
        meaning = self._parser.parse(raw, source_text=source_text)
        if meaning is not None or not self._parser.has_missing_semantic_target(raw):
            return meaning
        retry_context = dict(request.context)
        constraints_value = request.context.get("constraints")
        retry_constraints = (
            list(constraints_value) if isinstance(constraints_value, list) else []
        )
        retry_context["plugin_prompt_override"] = "\n".join(
            (
                prompt,
                "# Contract Repair",
                "前回のInput Meaning結果は、意味上の対象を持つquestion、request、または"
                "commandでtarget=nullだったため契約違反である。Raw User TextをCore規則で"
                "分類せず、会話履歴を含むObservedInputの意味を再評価し、欠落した対象を"
                "type/idへ構造化してJSONオブジェクト全体を一度だけ再出力する。",
            )
        )
        retry_context["constraints"] = [
            *retry_constraints,
            "意味上の対象が欠落したtarget契約を修復する",
        ]
        retry_request = Activity(
            activity_type=request.activity_type,
            goal="欠落した意味対象をStructuredInputMeaningへ再構造化する",
            context=retry_context,
            source_event_id=request.source_event_id,
        )
        try:
            retried_raw = await self._model.interpret_input_meaning(retry_request)
        except Exception:
            return None
        return self._parser.parse(retried_raw, source_text=source_text)


class InternalDirectivePlanner:
    def __init__(
        self,
        model: InternalDirectiveModel,
        *,
        prompt_builder: InternalDirectivePromptBuilder,
        parser: InternalDirectiveJsonParser | None = None,
        normalizer: InternalDirectiveCandidateNormalizer | None = None,
        interaction_intention_observer: (
            InteractionIntentionShadowObserver | None
        ) = None,
    ) -> None:
        self._model = model
        self._prompt_builder = prompt_builder
        self._parser = parser or InternalDirectiveJsonParser()
        self._normalizer = normalizer or InternalDirectiveCandidateNormalizer()
        self._interaction_intention_observer = (
            interaction_intention_observer or InteractionIntentionShadowObserver()
        )

    async def plan(
        self,
        activity: Activity,
        meaning: StructuredInputMeaning,
        planning_input: dict[str, object],
        *,
        character_profile: dict[str, object],
    ) -> InternalDirective | None:
        """既存互換API。Interaction IntentionはShadow観測だけ行う。"""

        observation = await self.plan_with_observation(
            activity,
            meaning,
            planning_input,
            character_profile=character_profile,
        )
        return observation.directive if observation is not None else None

    async def plan_with_observation(
        self,
        activity: Activity,
        meaning: StructuredInputMeaning,
        planning_input: dict[str, object],
        *,
        character_profile: dict[str, object],
    ) -> InternalDirectivePlanningObservation | None:
        """既存Directive候補とInteraction IntentionのShadow比較を返す。"""

        prompt = self._prompt_builder.build(
            meaning,
            planning_input,
            character_profile=character_profile,
        )
        request = Activity(
            activity_type=ActivityType.BEHAVIOR_PLANNING,
            goal="StructuredInputMeaningからInternalDirective候補を生成する",
            context={
                "plugin_prompt_override": prompt,
                "llm_role": "internal_directive_planner",
                "event_id": activity.context.get("event_id"),
                "trace_context": activity.context.get("trace_context"),
                "structured_input_meaning": meaning.as_context(),
                "constraints": [
                    "Raw User Textを再解釈しない",
                    "Activityの実行可否を確定しない",
                    "発話本文を生成しない",
                ],
            },
            source_event_id=activity.source_event_id,
        )
        try:
            raw = await self._model.plan_internal_directive(request)
        except Exception:
            return None
        directive = self._parser.parse(raw)
        if directive is None:
            return None
        normalized = self._normalizer.normalize(
            meaning,
            directive,
            planning_input,
        )
        return self._interaction_intention_observer.observe(
            meaning,
            normalized,
            planning_input,
            comparison_stage="normalized_internal_directive_candidate",
        )
