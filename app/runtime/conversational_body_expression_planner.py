from __future__ import annotations

from app.domain.avatar_performance import (
    AvatarBlendMode,
    AvatarContinuity,
    AvatarMotionIntent,
    AvatarPerformanceTrack,
    AvatarPoseIntent,
    AvatarTrackChannel,
)
from app.domain.body import BodyActivityContext, BodyExpressionRequest
from app.domain.body_speech import SpeechCoupledBodyExpressionRequest
from app.runtime.body_expression_planner import BodyExpressionPlanner


class ConversationalBodyExpressionPlanner(BodyExpressionPlanner):
    """人格的な演技Intentへ、発話動作と明示的な身体Actionを重ねる。"""

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
            tracks.extend(
                self._body_action_tracks(
                    request,
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

    @classmethod
    def _body_action_tracks(
        cls,
        request: SpeechCoupledBodyExpressionRequest,
        *,
        segment_index: int,
        start_offset_ms: int,
        duration_ms: int,
    ) -> tuple[AvatarPerformanceTrack, ...]:
        if not request.body_actions:
            return ()
        available = max(1000, duration_ms)
        tracks: list[AvatarPerformanceTrack] = []
        for action in request.body_actions:
            pose_specs = cls._pose_specs(action)
            if pose_specs:
                for channel, pose in pose_specs:
                    tracks.append(
                        cls._action_pose_track(
                            track_id=f"segment-{segment_index}-{channel.value}-{action}",
                            channel=channel,
                            start_offset_ms=start_offset_ms,
                            duration_ms=min(1800, max(1000, available)),
                            pose=pose,
                            layer_priority=360,
                            hold=True,
                        )
                    )
                continue

            if action == "blink":
                tracks.append(
                    cls._action_motion_track(
                        track_id=f"segment-{segment_index}-blink",
                        channel=AvatarTrackChannel.HEAD,
                        start_offset_ms=start_offset_ms,
                        duration_ms=520,
                        name="blink",
                        repetitions=1,
                        layer_priority=360,
                    )
                )
                continue

            specifications: tuple[tuple[AvatarTrackChannel, str, int, int], ...]
            if action == "right_hand_wave":
                specifications = ((AvatarTrackChannel.RIGHT_ARM, "wave", 3, 2400),)
            elif action == "left_hand_wave":
                specifications = ((AvatarTrackChannel.LEFT_ARM, "wave", 3, 2400),)
            elif action == "both_hands_wave":
                specifications = (
                    (AvatarTrackChannel.LEFT_ARM, "wave", 3, 2400),
                    (AvatarTrackChannel.RIGHT_ARM, "wave", 3, 2400),
                )
            elif action == "head_circle":
                specifications = ((AvatarTrackChannel.HEAD, "head_circle", 1, 2300),)
            elif action == "bow":
                specifications = ((AvatarTrackChannel.TORSO, "bow", 1, 2200),)
            elif action == "jump":
                specifications = ((AvatarTrackChannel.TORSO, "jump", 1, 1800),)
            elif action == "body_sway":
                specifications = ((AvatarTrackChannel.TORSO, "body_sway", 3, 3000),)
            elif action == "body_twist":
                specifications = ((AvatarTrackChannel.TORSO, "body_twist", 2, 2600),)
            else:
                continue

            for channel, motion_name, repetitions, requested_duration in specifications:
                tracks.append(
                    cls._action_motion_track(
                        track_id=(
                            f"segment-{segment_index}-{channel.value}-{motion_name}"
                        ),
                        channel=channel,
                        start_offset_ms=start_offset_ms,
                        duration_ms=min(max(1000, available), requested_duration),
                        name=motion_name,
                        repetitions=repetitions,
                        layer_priority=340,
                    )
                )
        return tuple(tracks)

    @staticmethod
    def _pose_specs(
        action: str,
    ) -> tuple[tuple[AvatarTrackChannel, AvatarPoseIntent], ...]:
        if action == "right_hand_raise":
            return (
                (
                    AvatarTrackChannel.RIGHT_ARM,
                    AvatarPoseIntent(
                        right_arm_raise=1.0,
                        right_arm_in=-0.08,
                        responsiveness=0.68,
                    ),
                ),
            )
        if action == "left_hand_raise":
            return (
                (
                    AvatarTrackChannel.LEFT_ARM,
                    AvatarPoseIntent(
                        left_arm_raise=1.0,
                        left_arm_in=-0.08,
                        responsiveness=0.68,
                    ),
                ),
            )
        if action == "both_hands_raise":
            return (
                (
                    AvatarTrackChannel.LEFT_ARM,
                    AvatarPoseIntent(
                        left_arm_raise=1.0,
                        left_arm_in=-0.08,
                        responsiveness=0.68,
                    ),
                ),
                (
                    AvatarTrackChannel.RIGHT_ARM,
                    AvatarPoseIntent(
                        right_arm_raise=1.0,
                        right_arm_in=-0.08,
                        responsiveness=0.68,
                    ),
                ),
            )
        if action == "eyes_close":
            return (
                (
                    AvatarTrackChannel.FACE,
                    AvatarPoseIntent(eye_closure=1.0, responsiveness=0.82),
                ),
            )
        if action == "eyes_open":
            return (
                (
                    AvatarTrackChannel.FACE,
                    AvatarPoseIntent(eye_closure=0.0, responsiveness=0.82),
                ),
            )
        if action == "mouth_open":
            return (
                (
                    AvatarTrackChannel.FACE,
                    AvatarPoseIntent(mouth_open=1.0, responsiveness=0.78),
                ),
            )
        if action == "mouth_close":
            return (
                (
                    AvatarTrackChannel.FACE,
                    AvatarPoseIntent(mouth_open=0.0, responsiveness=0.78),
                ),
            )
        return ()

    @staticmethod
    def _action_pose_track(
        *,
        track_id: str,
        channel: AvatarTrackChannel,
        start_offset_ms: int,
        duration_ms: int,
        pose: AvatarPoseIntent,
        layer_priority: int,
        hold: bool,
    ) -> AvatarPerformanceTrack:
        return AvatarPerformanceTrack(
            track_id=track_id,
            channel=channel,
            start_offset_ms=start_offset_ms,
            duration_ms=duration_ms,
            fade_in_ms=min(520, duration_ms),
            fade_out_ms=0 if hold else min(420, duration_ms),
            blend_mode=AvatarBlendMode.OVERRIDE,
            continuity=AvatarContinuity.CURRENT,
            hold=hold,
            layer_priority=layer_priority,
            pose=pose,
        )

    @staticmethod
    def _action_motion_track(
        *,
        track_id: str,
        channel: AvatarTrackChannel,
        start_offset_ms: int,
        duration_ms: int,
        name: str,
        repetitions: int,
        layer_priority: int,
    ) -> AvatarPerformanceTrack:
        return AvatarPerformanceTrack(
            track_id=track_id,
            channel=channel,
            start_offset_ms=start_offset_ms,
            duration_ms=duration_ms,
            fade_in_ms=min(140, duration_ms),
            fade_out_ms=min(280, duration_ms),
            blend_mode=AvatarBlendMode.ADDITIVE,
            continuity=AvatarContinuity.CURRENT,
            hold=False,
            layer_priority=layer_priority,
            motion=AvatarMotionIntent(
                name=name,
                intensity=1.0,
                amplitude=1.0,
                tempo=1.0,
                repetitions=repetitions,
                body_participation=(1.0 if channel == AvatarTrackChannel.TORSO else 0.25),
            ),
        )
