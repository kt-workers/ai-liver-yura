from __future__ import annotations

from app.domain.avatar_performance import (
    AvatarBlendMode,
    AvatarGazeIntent,
    AvatarMotionIntent,
    AvatarPerformanceTrack,
    AvatarTrackChannel,
)
from app.domain.body import (
    BodyActivityContext,
    BodyAttentionBehavior,
    BodyAttentionIntent,
    BodyExpressionRequest,
)


class BodyExpressionPlanner:
    """高レベルな身体表現要求を、独立して重なる身体Trackへ展開する。

    全身プリセットを選ぶのではなく、agreement、approach、openness等の意味軸から
    首・胴体・左右腕の手続き的なプリミティブを個別に生成する。
    """

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
        tracks: list[AvatarPerformanceTrack] = []
        attention = request.attention or self._attention_from_context(activity_context)
        if attention is not None:
            tracks.append(
                self._attention_track(
                    attention,
                    segment_index=segment_index,
                    start_offset_ms=start_offset_ms,
                    duration_ms=duration_ms,
                )
            )

        tracks.extend(
            self._semantic_motion_tracks(
                request,
                segment_index=segment_index,
                start_offset_ms=start_offset_ms,
                duration_ms=duration_ms,
            )
        )
        if not any(track.motion is not None for track in tracks) and legacy_gesture:
            tracks.append(
                self._legacy_motion_track(
                    legacy_gesture,
                    legacy_gesture_intensity,
                    segment_index=segment_index,
                    start_offset_ms=start_offset_ms,
                    duration_ms=duration_ms,
                )
            )
        return tuple(tracks)

    @staticmethod
    def _attention_from_context(
        context: BodyActivityContext | None,
    ) -> BodyAttentionIntent | None:
        if context is None or context.attention_target is None:
            return None
        freedom = context.gaze_freedom
        return BodyAttentionIntent(
            target=context.attention_target,
            behavior=BodyAttentionBehavior.MAINTAIN,
            engagement=context.engagement,
            avoidance=0.0,
            eye_follow=1.0,
            head_follow=max(0.15, 0.7 - freedom * 0.35),
            body_follow=max(0.0, 0.28 - freedom * 0.2),
        )

    @staticmethod
    def _attention_track(
        attention: BodyAttentionIntent,
        *,
        segment_index: int,
        start_offset_ms: int,
        duration_ms: int,
    ) -> AvatarPerformanceTrack:
        visible_engagement = attention.engagement * (1.0 - attention.avoidance)
        behavior = attention.behavior.value
        target = attention.target
        if attention.behavior == BodyAttentionBehavior.AVOID:
            behavior = "avoid"
            visible_engagement = max(attention.engagement, attention.avoidance)
        return AvatarPerformanceTrack(
            track_id=f"segment-{segment_index}-body-attention",
            channel=AvatarTrackChannel.ATTENTION,
            start_offset_ms=start_offset_ms,
            duration_ms=duration_ms,
            fade_in_ms=min(180, duration_ms),
            fade_out_ms=min(260, duration_ms),
            blend_mode=AvatarBlendMode.OVERRIDE,
            hold=True,
            layer_priority=110,
            attention=AvatarGazeIntent(
                target=target,
                behavior=behavior,
                intensity=visible_engagement,
                eye_follow=attention.eye_follow,
                head_follow=attention.head_follow,
                body_follow=attention.body_follow,
            ),
        )

    def _semantic_motion_tracks(
        self,
        request: BodyExpressionRequest,
        *,
        segment_index: int,
        start_offset_ms: int,
        duration_ms: int,
    ) -> tuple[AvatarPerformanceTrack, ...]:
        expression = request.expression
        if expression.intensity <= 0.0:
            return ()

        tracks: list[AvatarPerformanceTrack] = []
        emphasis_offset = self._emphasis_offset(request, duration_ms)

        agreement_strength = abs(expression.agreement) * expression.intensity
        if agreement_strength >= 0.12:
            name = "nod" if expression.agreement > 0 else "head_shake"
            repetitions = max(1, min(4, round(1 + agreement_strength * 3)))
            tracks.append(
                self._motion_track(
                    track_id=f"segment-{segment_index}-{name}",
                    channel=AvatarTrackChannel.HEAD,
                    start_offset_ms=start_offset_ms + emphasis_offset,
                    available_duration_ms=max(100, duration_ms - emphasis_offset),
                    name=name,
                    intensity=agreement_strength,
                    amplitude=0.18 + agreement_strength * 0.82,
                    tempo=0.75 + expression.arousal * 1.15,
                    repetitions=repetitions,
                    body_participation=max(
                        0.0,
                        (agreement_strength - 0.55) * 0.9,
                    ),
                    layer_priority=230,
                )
            )

        approach_strength = abs(expression.approach) * expression.intensity
        if approach_strength >= 0.12:
            tracks.append(
                self._motion_track(
                    track_id=f"segment-{segment_index}-approach",
                    channel=AvatarTrackChannel.TORSO,
                    start_offset_ms=start_offset_ms + min(120, duration_ms // 8),
                    available_duration_ms=max(100, duration_ms - min(120, duration_ms // 8)),
                    name=(
                        "lean_forward"
                        if expression.approach > 0
                        else "lean_back"
                    ),
                    intensity=approach_strength,
                    amplitude=0.12 + approach_strength * 0.68,
                    tempo=0.55 + expression.arousal * 0.65,
                    repetitions=1,
                    body_participation=1.0,
                    layer_priority=150,
                )
            )

        surprise_strength = expression.surprise * expression.intensity
        if surprise_strength >= 0.18:
            tracks.append(
                self._motion_track(
                    track_id=f"segment-{segment_index}-surprise-recoil",
                    channel=AvatarTrackChannel.TORSO,
                    start_offset_ms=start_offset_ms,
                    available_duration_ms=min(duration_ms, 900),
                    name="recoil",
                    intensity=surprise_strength,
                    amplitude=0.2 + surprise_strength * 0.75,
                    tempo=1.0 + expression.arousal,
                    repetitions=1,
                    body_participation=1.0,
                    layer_priority=260,
                )
            )

        closure_strength = (1.0 - expression.openness) * expression.intensity
        opening_strength = expression.openness * expression.warmth * expression.intensity
        if closure_strength >= 0.48:
            tracks.extend(
                self._paired_arm_tracks(
                    segment_index=segment_index,
                    start_offset_ms=start_offset_ms + min(160, duration_ms // 6),
                    duration_ms=max(100, duration_ms - min(160, duration_ms // 6)),
                    name="draw_in",
                    strength=closure_strength,
                    tempo=0.55 + expression.tension * 0.55,
                    layer_priority=145,
                )
            )
        elif opening_strength >= 0.56 and expression.approach > 0.1:
            tracks.extend(
                self._paired_arm_tracks(
                    segment_index=segment_index,
                    start_offset_ms=start_offset_ms + min(180, duration_ms // 5),
                    duration_ms=max(100, duration_ms - min(180, duration_ms // 5)),
                    name="open_outward",
                    strength=opening_strength,
                    tempo=0.5 + expression.arousal * 0.5,
                    layer_priority=140,
                )
            )

        if expression.assertiveness * expression.intensity >= 0.62:
            strength = expression.assertiveness * expression.intensity
            tracks.append(
                self._motion_track(
                    track_id=f"segment-{segment_index}-straighten",
                    channel=AvatarTrackChannel.TORSO,
                    start_offset_ms=start_offset_ms,
                    available_duration_ms=duration_ms,
                    name="straighten",
                    intensity=strength,
                    amplitude=0.12 + strength * 0.45,
                    tempo=0.55 + expression.arousal * 0.55,
                    repetitions=1,
                    body_participation=1.0,
                    layer_priority=135,
                )
            )

        return tuple(tracks)

    @staticmethod
    def _emphasis_offset(request: BodyExpressionRequest, duration_ms: int) -> int:
        if not request.speech_emphasis:
            return min(220, duration_ms // 5)
        strongest = max(item.strength for item in request.speech_emphasis)
        ratio = 0.18 + (1.0 - strongest) * 0.18
        return min(duration_ms - 100, max(0, round(duration_ms * ratio)))

    @classmethod
    def _paired_arm_tracks(
        cls,
        *,
        segment_index: int,
        start_offset_ms: int,
        duration_ms: int,
        name: str,
        strength: float,
        tempo: float,
        layer_priority: int,
    ) -> tuple[AvatarPerformanceTrack, AvatarPerformanceTrack]:
        common = {
            "start_offset_ms": start_offset_ms,
            "available_duration_ms": duration_ms,
            "name": name,
            "intensity": strength,
            "amplitude": 0.16 + strength * 0.68,
            "tempo": tempo,
            "repetitions": 1,
            "body_participation": 0.2,
            "layer_priority": layer_priority,
        }
        return (
            cls._motion_track(
                track_id=f"segment-{segment_index}-left-arm-{name}",
                channel=AvatarTrackChannel.LEFT_ARM,
                direction="left",
                **common,
            ),
            cls._motion_track(
                track_id=f"segment-{segment_index}-right-arm-{name}",
                channel=AvatarTrackChannel.RIGHT_ARM,
                direction="right",
                **common,
            ),
        )

    @staticmethod
    def _motion_track(
        *,
        track_id: str,
        channel: AvatarTrackChannel,
        start_offset_ms: int,
        available_duration_ms: int,
        name: str,
        intensity: float,
        amplitude: float,
        tempo: float,
        repetitions: int,
        body_participation: float,
        layer_priority: int,
        direction: str | None = None,
    ) -> AvatarPerformanceTrack:
        duration_ms = max(100, min(available_duration_ms, 500 + repetitions * 320))
        return AvatarPerformanceTrack(
            track_id=track_id,
            channel=channel,
            start_offset_ms=start_offset_ms,
            duration_ms=duration_ms,
            fade_in_ms=min(140, duration_ms),
            fade_out_ms=min(240, duration_ms),
            blend_mode=AvatarBlendMode.ADDITIVE,
            hold=False,
            layer_priority=layer_priority,
            motion=AvatarMotionIntent(
                name=name,
                intensity=min(1.0, intensity),
                amplitude=min(1.5, amplitude),
                tempo=min(3.0, max(0.25, tempo)),
                repetitions=repetitions,
                body_participation=min(1.0, max(0.0, body_participation)),
                direction=direction,
            ),
        )

    @classmethod
    def _legacy_motion_track(
        cls,
        name: str,
        intensity: float,
        *,
        segment_index: int,
        start_offset_ms: int,
        duration_ms: int,
    ) -> AvatarPerformanceTrack:
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

        return cls._motion_track(
            track_id=f"segment-{segment_index}-{channel.value}",
            channel=channel,
            start_offset_ms=start_offset_ms,
            available_duration_ms=duration_ms,
            name=name,
            intensity=intensity,
            amplitude=max(0.15, intensity),
            tempo=tempo,
            repetitions=repetitions,
            body_participation=min(1.0, body_participation),
            layer_priority=200,
        )
