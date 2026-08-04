from __future__ import annotations

from typing import Any

from app.domain.actions import ActionPlan, ActionResource, ActionType
from app.domain.activities import Activity
from app.domain.body import BodyActivityContext, EmbodiedExpressionIntent
from app.domain.body_speech import SpeechCoupledBodyExpressionRequest
from app.domain.character_response import (
    CharacterResponse,
    ReactionPlan,
    ReactionSegment,
    VoiceIntent,
)
from app.runtime.action_planner import ActionPlanner as CoreActionPlanner
from app.runtime.avatar_performance_planner import AvatarPerformancePlanner
from app.runtime.body_activity_context_builder import BodyActivityContextBuilder
from app.runtime.body_spatial_command_resolver import BodySpatialCommandResolver


class AvatarPerformanceActionPlanner(CoreActionPlanner):
    """既存Action計画を維持し、Body向けの意味的要求を付与する。"""

    def __init__(
        self,
        *args: Any,
        avatar_performance_planner: AvatarPerformancePlanner | None = None,
        body_activity_context_builder: BodyActivityContextBuilder | None = None,
        body_spatial_command_resolver: BodySpatialCommandResolver | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._avatar_performance_planner = (
            avatar_performance_planner or AvatarPerformancePlanner()
        )
        self._body_activity_context_builder = (
            body_activity_context_builder or BodyActivityContextBuilder()
        )
        self._body_spatial_command_resolver = (
            body_spatial_command_resolver or BodySpatialCommandResolver()
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
        speech_act = self._speech_act(activity)
        command_attention = self._body_spatial_command_resolver.resolve(activity)
        compatibility_performance = self._avatar_performance_planner.plan(
            plan,
            source_activity_id=activity.activity_id,
            output_unit_id=output_unit_id,
            priority=self._output_priority(activity.activity_type),
            body_context=body_context,
        )
        actions: list[ActionPlan] = []
        for index, segment in enumerate(plan.segments):
            body_request = SpeechCoupledBodyExpressionRequest(
                source_activity_id=activity.activity_id,
                output_unit_id=output_unit_id,
                expression=(
                    segment.embodied_expression
                    or self._fallback_expression_intent(
                        activity,
                        segment,
                        body_context,
                    )
                ),
                attention=segment.attention_intent or command_attention,
                facial_expression=segment.expression,
                facial_intensity=segment.expression_intensity,
                speech_emphasis=segment.speech_emphasis,
                priority=self._output_priority(activity.activity_type),
                duration_hint_ms=self._duration_hint_ms(segment),
                speech_act=speech_act,
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
    def _speech_act(activity: Activity) -> str:
        event_payload = activity.context.get("event_payload")
        candidates = (
            activity.context.get("behavior_plan"),
            event_payload.get("behavior_plan")
            if isinstance(event_payload, dict)
            else None,
        )
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            value = candidate.get("speech_act")
            if isinstance(value, str) and value.strip():
                return value.strip().lower()
        return "statement"

    @classmethod
    def _fallback_expression_intent(
        cls,
        activity: Activity,
        segment: ReactionSegment,
        body_context: BodyActivityContext,
    ) -> EmbodiedExpressionIntent:
        """LLMが演技Intentを省略した場合に、Body向け意味軸を補う。

        発話に伴う細かな首・胴体の動きはBody側の発話連動Plannerが生成する。
        ここでは感情・発話行為に由来する継続的な態度だけを補う。
        """

        gesture = (segment.gesture or "").strip().lower()
        expression_name = (segment.expression or "neutral").strip().lower()
        speech_act = cls._speech_act(activity)
        intensity = max(
            0.28,
            min(
                1.0,
                max(
                    segment.gesture_intensity if gesture else 0.0,
                    segment.expression_intensity * 0.52,
                    body_context.movement_energy * 0.85,
                ),
            ),
        )
        agreement = 0.0
        approach = 0.0
        openness = 0.55
        warmth = 0.55
        valence = 0.0
        arousal = min(1.0, 0.2 + body_context.movement_energy * 0.55)
        tension = 0.0
        surprise = 0.0
        assertiveness = 0.0

        if expression_name in {"smile", "soft_smile", "happy"}:
            valence = 0.45
            openness = 0.68
            warmth = 0.78
        elif expression_name == "curious":
            valence = 0.18
            approach = 0.18
            openness = 0.62
            warmth = 0.62
            arousal = min(1.0, arousal + 0.18)
        elif expression_name == "sad":
            valence = -0.55
            approach = -0.18
            openness = 0.28
            warmth = 0.42
            tension = 0.32
        elif expression_name in {"angry", "disgusted"}:
            valence = -0.62
            openness = 0.22
            warmth = 0.18
            tension = 0.78
            assertiveness = 0.72
        elif expression_name == "surprised":
            surprise = 0.82
            arousal = 0.88
            openness = 0.72

        if speech_act == "greeting":
            approach = max(approach, 0.22)
            openness = max(openness, 0.72)
            warmth = max(warmth, 0.78)
        elif speech_act == "question":
            approach = max(approach, 0.30)
            openness = max(openness, 0.60)
        elif speech_act == "acknowledgement":
            agreement = max(agreement, 0.42)
            approach = max(approach, 0.12)
        elif speech_act == "answer":
            approach = max(approach, 0.14)
            agreement = max(agreement, 0.16)
        elif speech_act in {"request", "proposal", "command"}:
            approach = max(approach, 0.20)
            assertiveness = max(assertiveness, 0.42)
        elif speech_act == "closing":
            approach = min(approach, -0.15)

        if gesture in {"small_nod", "nod"}:
            agreement = max(agreement, intensity)
        elif gesture == "head_shake":
            agreement = -intensity
            approach = min(approach, -intensity * 0.35)
            openness = min(openness, max(0.0, 0.5 - intensity * 0.35))
        elif gesture in {"lean_forward", "bounce"}:
            approach = max(approach, intensity)
        elif gesture in {"lean_back", "recoil"}:
            approach = min(approach, -intensity)
        elif gesture in {
            "wave",
            "raise_hand",
            "right_hand_raise",
            "left_wave",
            "left_hand_raise",
        }:
            approach = max(approach, intensity * 0.35)
            openness = max(openness, min(1.0, 0.55 + intensity * 0.4))
            warmth = max(warmth, min(1.0, 0.55 + intensity * 0.4))

        return EmbodiedExpressionIntent(
            attitude=expression_name or "neutral",
            intensity=intensity,
            valence=valence,
            arousal=arousal,
            tension=tension,
            openness=openness,
            approach=approach,
            agreement=agreement,
            surprise=surprise,
            assertiveness=assertiveness,
            warmth=warmth,
        )
