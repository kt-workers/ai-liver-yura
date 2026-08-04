from __future__ import annotations

from app.domain.avatar_performance import (
    AvatarBlendMode,
    AvatarContinuity,
    AvatarMotionIntent,
    AvatarPerformanceTrack,
    AvatarTrackChannel,
)
from app.domain.body import BodyActivityContext, BodyExpressionRequest
from app.domain.body_speech import SpeechCoupledBodyExpressionRequest
from app.runtime.body_expression_planner import BodyExpressionPlanner


class ConversationalBodyExpressionPlanner(BodyExpressionPlanner):
    """人格的な演技Intentへ、Body主体の発話連動動作を重ねる。"""

    def compile(
        self,
        request: BodyExpressionRequest,
        *,
        activity_context: BodyActivityContext | None,
        segment_index: int,
        start_offset_ms: int,
        duration_ms: int,
        legacy_gesture: str | None = None,
        legacy_gesture_intensity: float = 1.0,
    ) -> tuple[AvatarPerformanceTrack, ...]:
        tracks = list(
            super().compile(
                request,
                activity_context=activity_context,
                segment_index=segment_index,
                start_offset_ms=start_offset_ms,
                duration_ms=duration_ms,
                legacy_gesture=legacy_gesture,
                legacy_gesture_intensity=legacy_gesture_intensity,
            )
        )
        if isinstance(request, SpeechCoupledBodyExpressionRequest):
            tracks.extend(
                self._speech_tracks(
                    request,
                    activity_context=activity_context,
                    segment_index=segment_index,
                    start_offset_ms=start_offset_ms,
                    duration_ms=duration_ms,
                )
            )
        return tuple(tracks)

    @staticmethod
    def _speech_tracks(
        request: SpeechCoupledBodyExpressionRequest,
        *,
        activity_context: BodyActivityContext | None,
        segment_index: int,
        start_offset_ms: int,
        duration_ms: int,
    ) -> tuple[AvatarPerformanceTrack, ...]:
        duration_ms = max(600, duration_ms)
        energy = (
            activity_context.movement_energy
            if activity_context is not None
            else 0.35
        )
        engagement = (
            activity_context.engagement
            if activity_context is not None
            else 0.5
        )
        arousal = request.expression.arousal
        intensity = min(
            0.9,
            max(0.36, 0.30 + energy * 0.36 + engagement * 0.12 + arousal * 0.18),
        )
        direction = (
            "left"
            if sum(ord(character) for character in request.request_id) % 2 == 0
            else "right"
        )
        head_repetitions = max(2, min(8, round(duration_ms / 900)))
        torso_repetitions = max(1, min(5, round(duration_ms / 1600)))

        tracks: list[AvatarPerformanceTrack] = [
            AvatarPerformanceTrack(
                track_id=f"segment-{segment_index}-speech-cadence",
                channel=AvatarTrackChannel.HEAD,
                start_offset_ms=start_offset_ms,
                duration_ms=duration_ms,
                fade_in_ms=min(220, duration_ms),
                fade_out_ms=min(320, duration_ms),
                blend_mode=AvatarBlendMode.ADDITIVE,
                continuity=AvatarContinuity.CURRENT,
                hold=False,
                layer_priority=75,
                motion=AvatarMotionIntent(
                    name="speech_cadence",
                    intensity=intensity,
                    amplitude=min(1.5, 0.52 + energy * 0.34),
                    tempo=min(3.0, 0.72 + arousal * 0.48),
                    repetitions=head_repetitions,
                    body_participation=0.18,
                    direction=direction,
                ),
            ),
            AvatarPerformanceTrack(
                track_id=f"segment-{segment_index}-speech-sway",
                channel=AvatarTrackChannel.TORSO,
                start_offset_ms=start_offset_ms + min(100, duration_ms // 8),
                duration_ms=max(500, duration_ms - min(100, duration_ms // 8)),
                fade_in_ms=min(320, duration_ms),
                fade_out_ms=min(420, duration_ms),
                blend_mode=AvatarBlendMode.ADDITIVE,
                continuity=AvatarContinuity.CURRENT,
                hold=False,
                layer_priority=65,
                motion=AvatarMotionIntent(
                    name="speech_sway",
                    intensity=min(0.8, intensity * 0.78),
                    amplitude=min(1.5, 0.42 + energy * 0.42),
                    tempo=min(3.0, 0.48 + energy * 0.38),
                    repetitions=torso_repetitions,
                    body_participation=1.0,
                    direction=("right" if direction == "left" else "left"),
                ),
            ),
        ]

        if request.speech_act in {"question", "proposal"}:
            accent_duration = min(950, max(600, duration_ms // 3))
            tracks.append(
                AvatarPerformanceTrack(
                    track_id=f"segment-{segment_index}-question-tilt",
                    channel=AvatarTrackChannel.HEAD,
                    start_offset_ms=start_offset_ms + max(0, duration_ms - accent_duration),
                    duration_ms=accent_duration,
                    fade_in_ms=min(180, accent_duration),
                    fade_out_ms=min(280, accent_duration),
                    blend_mode=AvatarBlendMode.ADDITIVE,
                    continuity=AvatarContinuity.CURRENT,
                    hold=False,
                    layer_priority=105,
                    motion=AvatarMotionIntent(
                        name="question_tilt",
                        intensity=min(0.85, 0.46 + engagement * 0.30),
                        amplitude=0.72,
                        tempo=0.75,
                        repetitions=1,
                        body_participation=0.25,
                        direction=direction,
                    ),
                )
            )
        elif request.speech_act in {"greeting", "acknowledgement", "answer"}:
            accent_duration = min(850, duration_ms)
            tracks.append(
                AvatarPerformanceTrack(
                    track_id=f"segment-{segment_index}-speech-small-nod",
                    channel=AvatarTrackChannel.HEAD,
                    start_offset_ms=start_offset_ms + min(140, duration_ms // 8),
                    duration_ms=accent_duration,
                    fade_in_ms=min(120, accent_duration),
                    fade_out_ms=min(220, accent_duration),
                    blend_mode=AvatarBlendMode.ADDITIVE,
                    continuity=AvatarContinuity.CURRENT,
                    hold=False,
                    layer_priority=100,
                    motion=AvatarMotionIntent(
                        name="small_nod",
                        intensity=min(0.75, 0.38 + engagement * 0.24),
                        amplitude=0.52,
                        tempo=0.95,
                        repetitions=1,
                        body_participation=0.12,
                        direction=None,
                    ),
                )
            )

        return tuple(tracks)
