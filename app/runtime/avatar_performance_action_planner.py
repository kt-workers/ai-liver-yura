from __future__ import annotations

from typing import Any

from app.domain.actions import ActionPlan, ActionResource, ActionType
from app.domain.activities import Activity
from app.domain.character_response import (
    CharacterResponse,
    ReactionPlan,
    ReactionSegment,
    VoiceIntent,
)
from app.runtime.action_planner import ActionPlanner as CoreActionPlanner
from app.runtime.avatar_performance_planner import AvatarPerformancePlanner
from app.runtime.body_activity_context_builder import BodyActivityContextBuilder


class AvatarPerformanceActionPlanner(CoreActionPlanner):
    """既存Action計画を維持し、Body向け複合Performanceだけを付与する。"""

    def __init__(
        self,
        *args: Any,
        avatar_performance_planner: AvatarPerformancePlanner | None = None,
        body_activity_context_builder: BodyActivityContextBuilder | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._avatar_performance_planner = (
            avatar_performance_planner or AvatarPerformancePlanner()
        )
        self._body_activity_context_builder = (
            body_activity_context_builder or BodyActivityContextBuilder()
        )

    def _reaction_action_plans(
        self,
        activity: Activity,
        response: CharacterResponse | None,
        *,
        fallback_speech: str,
        output_unit_id: str,
        base_metadata: dict[str, object],
        skip_topic_memory: bool,
    ) -> list[ActionPlan]:
        plan = (
            response.effective_reaction_plan()
            if response is not None
            else ReactionPlan(
                (ReactionSegment(fallback_speech, voice_intent=VoiceIntent()),)
            )
        )
        body_context = self._body_activity_context_builder.build(activity)
        performance = self._avatar_performance_planner.plan(
            plan,
            source_activity_id=activity.activity_id,
            output_unit_id=output_unit_id,
            priority=self._output_priority(activity.activity_type),
            body_context=body_context,
        )
        actions: list[ActionPlan] = []
        for index, segment in enumerate(plan.segments):
            segment_metadata: dict[str, object] = {
                **base_metadata,
                "reaction_segment_index": index,
                "reaction_segment_count": len(plan.segments),
                "avatar_performance_id": performance.performance_id,
                "body_activity_context": body_context,
            }
            speak_metadata = {
                **segment_metadata,
                "voice_intent": segment.voice_intent,
                "pause_after_seconds": segment.pause_after_seconds,
                "speech_emphasis": segment.speech_emphasis,
            }
            if skip_topic_memory:
                speak_metadata["skip_topic_memory"] = True

            expression_metadata = {
                **segment_metadata,
                "avatar_performance_managed": True,
                "expression_intensity": segment.expression_intensity,
            }
            if index == 0:
                expression_metadata["avatar_performance_plan"] = performance

            actions.extend(
                (
                    ActionPlan(
                        action_type=ActionType.SPEAK,
                        text=segment.speech,
                        required_resources={ActionResource.MOUTH},
                        source_activity_id=activity.activity_id,
                        output_unit_id=output_unit_id,
                        metadata=speak_metadata,
                    ),
                    ActionPlan(
                        action_type=ActionType.UPDATE_SUBTITLE,
                        text=segment.speech,
                        required_resources={ActionResource.SUBTITLE},
                        source_activity_id=activity.activity_id,
                        output_unit_id=output_unit_id,
                        metadata=dict(segment_metadata),
                    ),
                    ActionPlan(
                        action_type=ActionType.CHANGE_EXPRESSION,
                        text=segment.expression,
                        required_resources={ActionResource.FACE},
                        source_activity_id=activity.activity_id,
                        output_unit_id=output_unit_id,
                        metadata=expression_metadata,
                    ),
                )
            )
            if segment.gesture:
                actions.append(
                    ActionPlan(
                        action_type=ActionType.MOVE,
                        text=segment.gesture,
                        required_resources={ActionResource.BODY},
                        source_activity_id=activity.activity_id,
                        output_unit_id=output_unit_id,
                        metadata={
                            **segment_metadata,
                            "avatar_performance_managed": True,
                            "gesture_intensity": segment.gesture_intensity,
                        },
                    )
                )
        return actions
