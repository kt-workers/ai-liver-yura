from __future__ import annotations

from dataclasses import replace
from typing import Mapping

from app.domain.activities import Activity
from app.domain.character_response import ResponseContext
from app.domain.semantic_utterance import SemanticUtterancePlan
from app.runtime.character_response_pipeline import (
    ResponseContextBuilder as BaseResponseContextBuilder,
)
from app.runtime.response_semantics_planner import ResponseSemanticsPlanner
from app.utils.trace import TraceLogger


class InternalStateAwareResponseContextBuilder(BaseResponseContextBuilder):
    """全Activity種別でEmotion／Driveと発話意味の投影規則を統一する。"""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._state_projection_trace_logger = TraceLogger()
        self._response_semantics_planner = ResponseSemanticsPlanner()

    def build(self, activity: Activity) -> ResponseContext:
        context = super().build(activity)
        event_payload = self._mapping(activity.context.get("event_payload"))
        autonomous_situation = self._mapping(
            event_payload.get(
                "autonomous_situation_context",
                activity.context.get("autonomous_situation_context"),
            )
        )

        emotion, emotion_source = self._first_mapping(
            ("event_payload", event_payload.get("emotion")),
            ("activity_context", activity.context.get("emotion")),
            ("autonomous_situation", autonomous_situation.get("emotion_state")),
        )
        drive, drive_source = self._first_mapping(
            ("event_payload", event_payload.get("drive")),
            ("activity_context", activity.context.get("drive")),
            ("autonomous_situation", autonomous_situation.get("drive_state")),
        )
        projected_drive = {
            str(key): float(value)
            for key, value in drive.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }

        projected = replace(
            context,
            emotion=dict(emotion),
            drive=projected_drive,
        )
        semantic_plan = self._response_semantics_planner.plan(projected)
        semantic_plan = self._attach_repetition_context(projected, semantic_plan)
        projected_memory = dict(projected.memory)
        projected_memory["semantic_utterance_plan"] = semantic_plan.as_context()
        projected = replace(projected, memory=projected_memory)

        self._state_projection_trace_logger.debug(
            "response_context_builder:internal_state_projected",
            source_activity_id=activity.activity_id,
            activity_type=projected.activity_type,
            emotion_source=emotion_source,
            drive_source=drive_source,
            emotion_available=bool(projected.emotion),
            drive_available=bool(projected.drive),
            emotion_keys=sorted(projected.emotion),
            drive_keys=sorted(projected.drive),
        )
        self._state_projection_trace_logger.debug(
            "response_semantics_planner:planned",
            source_activity_id=activity.activity_id,
            activity_type=projected.activity_type,
            speech_act=semantic_plan.speech_act,
            target=(semantic_plan.target.as_context() if semantic_plan.target else None),
            proposition_count=len(semantic_plan.propositions),
            question_budget=semantic_plan.question_budget,
            new_direction_budget=semantic_plan.new_direction_budget,
            response_length=semantic_plan.response_length,
            repetition_context_available=bool(
                semantic_plan.discourse_context.get("recent_speech_summary")
            ),
        )
        return projected

    @staticmethod
    def _attach_repetition_context(
        context: ResponseContext,
        semantic_plan: SemanticUtterancePlan,
    ) -> SemanticUtterancePlan:
        # Characterへraw内部状態を戻さず、反復回避に必要な直近発話だけを
        # finite discourse contextとして渡す。avoid_repetition無効時は投影しない。
        if context.constraints.get("avoid_repetition") is not True:
            return semantic_plan
        recent_speech = context.recent_speech_summary.strip()
        if not recent_speech:
            return semantic_plan
        discourse_context = dict(semantic_plan.discourse_context)
        discourse_context["recent_speech_summary"] = recent_speech
        discourse_context["repetition_policy"] = "avoid_semantic_and_phrasal_repeat"
        return replace(semantic_plan, discourse_context=discourse_context)

    @staticmethod
    def _mapping(value: object) -> Mapping[str, object]:
        return value if isinstance(value, Mapping) else {}

    @classmethod
    def _first_mapping(
        cls,
        *candidates: tuple[str, object],
    ) -> tuple[Mapping[str, object], str | None]:
        for source, value in candidates:
            mapping = cls._mapping(value)
            if mapping:
                return mapping, source
        return {}, None