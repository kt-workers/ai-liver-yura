from __future__ import annotations

from typing import Any

from app.domain.actions import ActionPlan, ActionResource, ActionType
from app.domain.activities import Activity
from app.domain.body import BodyExpressionRequest, EmbodiedExpressionIntent
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
    """既存Action計画を維持し、Body向けの意味的要求を付与する。"""

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
        compatibility_performance = self._avatar_performance_planner.plan(
            plan,
            source_activity_id=activity.activity_id,
            output_unit_id=output_unit_id,
            priority=self._output_priority(activity.activity_type),
            body_context=body_context,
        )
        actions: list[ActionPlan] = []
        for index, segment in enumerate(plan.segments):
            body_request = BodyExpressionRequest(
                source_activity_id=activity.activity_id,
                output_unit_id=output_unit_id,
                expression=(
                    segment.embodied_expression
                    or self._legacy_expression_intent(segment)
                ),
                attention=segment.attention_intent,
                facial_expression=segment.expression,
                facial_intensity=segment.expression_intensity,
                speech_emphasis=segment.speech_emphasis,
                priority=self._output_priority(activity.activity_type),
                duration_hint_ms=self._duration_hint_ms(segment),
            )
            segment_metadata: dict[str, object] = {
                **base_metadata,
                "reaction_segment_index": index,
                "reaction_segment_count": len(plan.segments),
                "avatar_performance_id": compatibility_performance.performance_id,
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
                "body_expression_request": body_request,
            }
            if index == 0:
                expression_metadata["avatar_performance_plan"] = (
                    compatibility_performance
                )

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
                            "body_expression_request": body_request,
                            "gesture_intensity": segment.gesture_intensity,
                        },
                    )
                )
        return actions

    @staticmethod
    def _duration_hint_ms(segment: ReactionSegment) -> int:
        speech_ms = round(len(segment.speech.strip()) / 8.0 * 1000)
        pause_ms = round(max(0.0, segment.pause_after_seconds) * 1000)
        return max(800, min(20_000, speech_ms + pause_ms))

    @staticmethod
    def _legacy_expression_intent(
        segment: ReactionSegment,
    ) -> EmbodiedExpressionIntent:
        """移行用gestureを身体部位指定ではない意味軸へ変換する。"""

        intensity = max(
            0.15,
            min(1.0, max(segment.expression_intensity, segment.gesture_intensity)),
        )
        gesture = (segment.gesture or "").strip().lower()
        agreement = 0.0
        approach = 0.0
        openness = 0.5
        warmth = 0.5
        arousal = intensity * 0.45
        attitude = segment.expression or "neutral"

        if gesture in {"small_nod", "nod"}:
            agreement = intensity
        elif gesture == "head_shake":
            agreement = -intensity
            approach = -intensity * 0.35
            openness = max(0.0, 0.5 - intensity * 0.35)
        elif gesture in {"lean_forward", "bounce"}:
            approach = intensity
        elif gesture in {"lean_back", "recoil"}:
            approach = -intensity
        elif gesture in {
            "wave",
            "raise_hand",
            "right_hand_raise",
            "left_wave",
            "left_hand_raise",
        }:
            approach = intensity * 0.35
            openness = min(1.0, 0.55 + intensity * 0.4)
            warmth = min(1.0, 0.55 + intensity * 0.4)

        return EmbodiedExpressionIntent(
            attitude=attitude,
            intensity=intensity if gesture else segment.expression_intensity * 0.35,
            valence=0.0,
            arousal=arousal,
            tension=0.0,
            openness=openness,
            approach=approach,
            agreement=agreement,
            surprise=1.0 if segment.expression == "surprised" else 0.0,
            assertiveness=0.0,
            warmth=warmth,
        )
