from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from app.domain.avatar_performance import (
    AvatarExpressionIntent,
    AvatarGestureIntent,
    AvatarPerformancePlan,
    AvatarPerformanceSegment,
)
from app.domain.character_response import ReactionPlan, ReactionSegment

PerformanceIdFactory = Callable[[], str]


class AvatarPerformancePlanner:
    """確定済みReactionPlanを再解釈せずAvatar演技計画へ変換する。"""

    def __init__(
        self,
        *,
        performance_id_factory: PerformanceIdFactory | None = None,
    ) -> None:
        self._performance_id_factory = performance_id_factory or (
            lambda: str(uuid4())
        )

    def plan(
        self,
        reaction_plan: ReactionPlan,
        *,
        source_activity_id: str,
        output_unit_id: str,
        priority: int,
    ) -> AvatarPerformancePlan:
        return AvatarPerformancePlan(
            performance_id=self._performance_id_factory(),
            source_activity_id=source_activity_id,
            output_unit_id=output_unit_id,
            priority=priority,
            segments=tuple(
                self._segment(segment) for segment in reaction_plan.segments
            ),
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
        # TTSエンジンや実音声長には依存せず、Web MVP用の暫定値だけを補完する。
        speech_ms = round(len(segment.speech.strip()) / 8.0 * 1000)
        pause_ms = round(segment.pause_after_seconds * 1000)
        return max(600, min(15_000, speech_ms + pause_ms))
