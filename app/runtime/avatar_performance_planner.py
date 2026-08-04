from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from app.domain.avatar_performance import (
    AvatarBlendMode,
    AvatarExpressionIntent,
    AvatarGestureIntent,
    AvatarGazeIntent,
    AvatarPerformancePlan,
    AvatarPerformanceSegment,
    AvatarPerformanceTrack,
    AvatarTrackChannel,
)
from app.domain.body import (
    BodyActivityContext,
    BodyAttentionBehavior,
    BodyAttentionIntent,
    BodyExpressionRequest,
    EmbodiedExpressionIntent,
)
from app.domain.character_response import ReactionPlan, ReactionSegment
from app.runtime.body_expression_planner import BodyExpressionPlanner

PerformanceIdFactory = Callable[[], str]


class AvatarPerformancePlanner:
    """Bodyの高レベル表現要求を実行可能なAvatar Trackへコンパイルする。"""

    def __init__(
        self,
        *,
        performance_id_factory: PerformanceIdFactory | None = None,
        body_expression_planner: BodyExpressionPlanner | None = None,
    ) -> None:
        self._performance_id_factory = performance_id_factory or (
            lambda: str(uuid4())
        )
        self._body_expression_planner = (
            body_expression_planner or BodyExpressionPlanner()
        )

    def plan(
        self,
        reaction_plan: ReactionPlan,
        *,
        source_activity_id: str,
        output_unit_id: str,
        priority: int,
        body_context: BodyActivityContext | None = None,
    ) -> AvatarPerformancePlan:
        segments: list[AvatarPerformanceSegment] = []
        tracks: list[AvatarPerformanceTrack] = []
        start_offset_ms = 0

        for index, reaction_segment in enumerate(reaction_plan.segments):
            segment = self._segment(reaction_segment)
            segments.append(segment)
            tracks.append(
                self._expression_track(
                    segment,
                    segment_index=index,
                    start_offset_ms=start_offset_ms,
                )
            )
            request = BodyExpressionRequest(
                source_activity_id=source_activity_id,
                output_unit_id=output_unit_id,
                expression=(
                    reaction_segment.embodied_expression
                    or EmbodiedExpressionIntent()
                ),
                attention=self._body_attention(reaction_segment),
                speech_emphasis=reaction_segment.speech_emphasis,
                priority=priority,
                duration_hint_ms=segment.duration_ms,
            )
            tracks.extend(
                self._body_expression_planner.compile(
                    request,
                    activity_context=body_context,
                    segment_index=index,
                    start_offset_ms=start_offset_ms,
                    duration_ms=segment.duration_ms,
                    legacy_gesture=reaction_segment.gesture,
                    legacy_gesture_intensity=reaction_segment.gesture_intensity,
                )
            )
            start_offset_ms += segment.duration_ms

        return AvatarPerformancePlan(
            performance_id=self._performance_id_factory(),
            source_activity_id=source_activity_id,
            output_unit_id=output_unit_id,
            priority=priority,
            segments=tuple(segments),
            tracks=tuple(tracks),
        )

    @staticmethod
    def _expression_track(
        segment: AvatarPerformanceSegment,
        *,
        segment_index: int,
        start_offset_ms: int,
    ) -> AvatarPerformanceTrack:
        return AvatarPerformanceTrack(
            track_id=f"segment-{segment_index}-expression",
            channel=AvatarTrackChannel.EXPRESSION,
            start_offset_ms=start_offset_ms,
            duration_ms=segment.duration_ms,
            fade_in_ms=segment.fade_in_ms,
            fade_out_ms=segment.fade_out_ms,
            blend_mode=AvatarBlendMode.OVERRIDE,
            hold=True,
            layer_priority=100,
            expression=segment.expression,
        )

    @staticmethod
    def _body_attention(segment: ReactionSegment) -> BodyAttentionIntent | None:
        if segment.attention_intent is not None:
            return segment.attention_intent
        gaze = segment.gaze
        if gaze is None:
            return None
        try:
            behavior = BodyAttentionBehavior(gaze.behavior)
        except ValueError:
            behavior = BodyAttentionBehavior.MAINTAIN
        return BodyAttentionIntent(
            target=gaze.target,
            behavior=behavior,
            engagement=gaze.intensity,
            avoidance=(
                gaze.intensity
                if behavior == BodyAttentionBehavior.AVOID
                else 0.0
            ),
            eye_follow=gaze.eye_follow,
            head_follow=gaze.head_follow,
            body_follow=gaze.body_follow,
        )

    @classmethod
    def _segment(cls, segment: ReactionSegment) -> AvatarPerformanceSegment:
        duration_ms = cls._estimate_duration_ms(segment)
        fade_in_ms = min(200, duration_ms)
        fade_out_ms = min(300, duration_ms)
        return AvatarPerformanceSegment(
            expression=AvatarExpressionIntent(
                name=segment.expression,
                intensity=segment.expression_intensity,
            ),
            gesture=(
                AvatarGestureIntent(
                    name=segment.gesture,
                    intensity=segment.gesture_intensity,
                )
                if segment.gesture is not None
                else None
            ),
            gaze=segment.gaze,
            duration_ms=duration_ms,
            fade_in_ms=fade_in_ms,
            fade_out_ms=fade_out_ms,
        )

    @staticmethod
    def _estimate_duration_ms(segment: ReactionSegment) -> int:
        # 実音声長が利用可能になるまでの暫定値。最終同期はBody側の再生時計で行う。
        speech_ms = round(len(segment.speech.strip()) / 8.0 * 1000)
        pause_ms = round(segment.pause_after_seconds * 1000)
        return max(600, min(15_000, speech_ms + pause_ms))
