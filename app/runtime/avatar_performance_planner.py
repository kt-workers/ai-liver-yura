from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from app.domain.avatar_performance import (
    AvatarBlendMode,
    AvatarExpressionIntent,
    AvatarGestureIntent,
    AvatarMotionIntent,
    AvatarPerformancePlan,
    AvatarPerformanceSegment,
    AvatarPerformanceTrack,
    AvatarTrackChannel,
)
from app.domain.character_response import ReactionPlan, ReactionSegment

PerformanceIdFactory = Callable[[], str]


class AvatarPerformancePlanner:
    """確定済みReactionPlanを再解釈せず複合Avatar演技計画へ変換する。"""

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
        segments: list[AvatarPerformanceSegment] = []
        tracks: list[AvatarPerformanceTrack] = []
        start_offset_ms = 0

        for index, reaction_segment in enumerate(reaction_plan.segments):
            segment = self._segment(reaction_segment)
            segments.append(segment)
            tracks.extend(
                self._tracks_for_segment(
                    reaction_segment,
                    segment=segment,
                    segment_index=index,
                    start_offset_ms=start_offset_ms,
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

    @classmethod
    def _tracks_for_segment(
        cls,
        reaction_segment: ReactionSegment,
        *,
        segment: AvatarPerformanceSegment,
        segment_index: int,
        start_offset_ms: int,
    ) -> tuple[AvatarPerformanceTrack, ...]:
        prefix = f"segment-{segment_index}"
        tracks: list[AvatarPerformanceTrack] = [
            AvatarPerformanceTrack(
                track_id=f"{prefix}-expression",
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
        ]
        if segment.gaze is not None:
            tracks.append(
                AvatarPerformanceTrack(
                    track_id=f"{prefix}-attention",
                    channel=AvatarTrackChannel.ATTENTION,
                    start_offset_ms=start_offset_ms,
                    duration_ms=segment.duration_ms,
                    fade_in_ms=segment.fade_in_ms,
                    fade_out_ms=segment.fade_out_ms,
                    blend_mode=AvatarBlendMode.OVERRIDE,
                    hold=True,
                    layer_priority=100,
                    attention=segment.gaze,
                )
            )
        if reaction_segment.gesture is not None:
            channel, intent = cls._motion_intent(reaction_segment)
            tracks.append(
                AvatarPerformanceTrack(
                    track_id=f"{prefix}-{channel.value}",
                    channel=channel,
                    start_offset_ms=start_offset_ms,
                    duration_ms=segment.duration_ms,
                    fade_in_ms=min(180, segment.duration_ms),
                    fade_out_ms=min(260, segment.duration_ms),
                    blend_mode=AvatarBlendMode.ADDITIVE,
                    hold=False,
                    layer_priority=200,
                    motion=intent,
                )
            )
        return tuple(tracks)

    @staticmethod
    def _motion_intent(
        segment: ReactionSegment,
    ) -> tuple[AvatarTrackChannel, AvatarMotionIntent]:
        name = segment.gesture or "idle"
        intensity = segment.gesture_intensity
        if name in {"small_nod", "nod", "head_tilt", "head_shake"}:
            channel = AvatarTrackChannel.HEAD
        elif name in {"wave", "raise_hand", "right_hand_raise"}:
            channel = AvatarTrackChannel.RIGHT_ARM
        elif name in {"left_wave", "left_hand_raise"}:
            channel = AvatarTrackChannel.LEFT_ARM
        else:
            channel = AvatarTrackChannel.TORSO

        repetitions = 1
        tempo = 1.0
        body_participation = 0.0
        if name in {"small_nod", "nod"}:
            repetitions = 2
            tempo = 1.05
        elif name == "head_shake":
            repetitions = max(1, min(4, round(1 + intensity * 3)))
            tempo = 0.9 + intensity * 0.8
            body_participation = max(0.0, (intensity - 0.6) * 1.5)
        elif name == "wave":
            repetitions = 3
            tempo = 1.1

        return channel, AvatarMotionIntent(
            name=name,
            intensity=intensity,
            amplitude=max(0.15, intensity),
            tempo=tempo,
            repetitions=repetitions,
            body_participation=min(1.0, body_participation),
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
