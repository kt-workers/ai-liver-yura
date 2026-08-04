from __future__ import annotations

from dataclasses import replace

from app.domain.avatar_performance import (
    AvatarBlendMode,
    AvatarContinuity,
    AvatarMotionIntent,
    AvatarPerformancePlan,
    AvatarPerformanceTrack,
    AvatarTrackChannel,
)
from app.domain.body import BodyActivityContext
from app.runtime.body_runtime import BodyRuntime


class LivingBodyRuntime(BodyRuntime):
    """無指示時も視認できる生理・注意・姿勢の微細動作を生成する。"""

    def _build_autonomous_plan(
        self,
        context: BodyActivityContext | None,
    ) -> AvatarPerformancePlan:
        base = super()._build_autonomous_plan(context)
        energy = context.movement_energy if context is not None else 0.3
        direction = "left" if self._tick_count % 2 == 0 else "right"
        tracks: list[AvatarPerformanceTrack] = []

        for track in base.tracks:
            motion = track.motion
            if motion is None:
                tracks.append(track)
                continue
            if motion.name == "breathing":
                tracks.append(
                    replace(
                        track,
                        motion=replace(
                            motion,
                            intensity=min(1.0, 0.72 + energy * 0.18),
                            amplitude=min(1.5, 0.62 + energy * 0.28),
                            tempo=min(3.0, 0.72 + energy * 0.35),
                        ),
                    )
                )
            elif motion.name == "micro_sway":
                tracks.append(
                    replace(
                        track,
                        motion=replace(
                            motion,
                            intensity=min(1.0, 0.52 + energy * 0.30),
                            amplitude=min(1.5, 0.48 + energy * 0.38),
                            tempo=min(3.0, 0.48 + energy * 0.30),
                            direction=direction,
                        ),
                    )
                )
            else:
                tracks.append(track)

        duration_ms = base.duration_ms
        blink_offset = min(duration_ms - 300, 620 + (self._tick_count % 4) * 310)
        tracks.extend(
            (
                AvatarPerformanceTrack(
                    track_id="autonomous-blink",
                    channel=AvatarTrackChannel.HEAD,
                    start_offset_ms=max(0, blink_offset),
                    duration_ms=280,
                    fade_in_ms=60,
                    fade_out_ms=90,
                    blend_mode=AvatarBlendMode.ADDITIVE,
                    continuity=AvatarContinuity.CURRENT,
                    hold=False,
                    layer_priority=-70,
                    motion=AvatarMotionIntent(
                        name="idle_blink",
                        intensity=1.0,
                        amplitude=1.0,
                        tempo=1.0,
                        repetitions=1,
                        body_participation=0.0,
                    ),
                ),
                AvatarPerformanceTrack(
                    track_id="autonomous-gaze-shift",
                    channel=AvatarTrackChannel.HEAD,
                    start_offset_ms=180,
                    duration_ms=max(800, duration_ms - 360),
                    fade_in_ms=420,
                    fade_out_ms=520,
                    blend_mode=AvatarBlendMode.ADDITIVE,
                    continuity=AvatarContinuity.CURRENT,
                    hold=False,
                    layer_priority=-90,
                    motion=AvatarMotionIntent(
                        name="idle_gaze_shift",
                        intensity=min(1.0, 0.38 + energy * 0.35),
                        amplitude=min(1.5, 0.45 + energy * 0.35),
                        tempo=0.55,
                        repetitions=1,
                        body_participation=0.12,
                        direction=direction,
                    ),
                ),
                AvatarPerformanceTrack(
                    track_id="autonomous-posture-adjust",
                    channel=AvatarTrackChannel.TORSO,
                    start_offset_ms=260,
                    duration_ms=max(900, duration_ms - 520),
                    fade_in_ms=520,
                    fade_out_ms=620,
                    blend_mode=AvatarBlendMode.ADDITIVE,
                    continuity=AvatarContinuity.CURRENT,
                    hold=False,
                    layer_priority=-95,
                    motion=AvatarMotionIntent(
                        name="idle_posture_adjust",
                        intensity=min(1.0, 0.30 + energy * 0.35),
                        amplitude=min(1.5, 0.40 + energy * 0.30),
                        tempo=0.45,
                        repetitions=1,
                        body_participation=1.0,
                        direction=("right" if direction == "left" else "left"),
                    ),
                ),
            )
        )
        return replace(base, tracks=tuple(tracks))
