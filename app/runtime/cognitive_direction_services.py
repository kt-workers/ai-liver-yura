from __future__ import annotations

from app.adapters.prompt.cognitive_direction_prompt_builders import (
    InputMeaningPromptBuilder,
    InternalDirectivePromptBuilder,
)
from app.domain.activities import Activity, ActivityType
from app.domain.cognitive_direction import (
    InternalDirective,
    StructuredInputMeaning,
)
from app.ports.cognitive_direction import (
    InputMeaningModel,
    InternalDirectiveModel,
)
from app.runtime.cognitive_direction_parsers import (
    InputMeaningJsonParser,
    InternalDirectiveJsonParser,
)


class InputMeaningInterpreter:
    def __init__(
        self,
        model: InputMeaningModel,
        *,
        prompt_builder: InputMeaningPromptBuilder | None = None,
        parser: InputMeaningJsonParser | None = None,
    ) -> None:
        self._model = model
        self._prompt_builder = prompt_builder or InputMeaningPromptBuilder()
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
        return self._parser.parse(raw, source_text=source_text)


class InternalDirectivePlanner:
    def __init__(
        self,
        model: InternalDirectiveModel,
        *,
        prompt_builder: InternalDirectivePromptBuilder | None = None,
        parser: InternalDirectiveJsonParser | None = None,
    ) -> None:
        self._model = model
        self._prompt_builder = prompt_builder or InternalDirectivePromptBuilder()
        self._parser = parser or InternalDirectiveJsonParser()

    async def plan(
        self,
        activity: Activity,
        meaning: StructuredInputMeaning,
        planning_input: dict[str, object],
        *,
        character_profile: dict[str, object],
    ) -> InternalDirective | None:
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
        return self._parser.parse(raw)


