from __future__ import annotations

import inspect
from contextlib import suppress

from app.domain.body import (
    BodyActivityContext,
    BodyAttentionBehavior,
    BodyAttentionIntent,
    BodyExpressionRequest,
    BodyPostureTendency,
    SpeechPresentationRequest,
)
from app.domain.body_pose_frame import BodyAttentionCandidate, BodyInnerMotionState
from app.ports.avatar_output import AvatarOutputPort
from app.ports.body_pose_output import BodyPoseFrameOutputPort
from app.runtime.body_runtime import BodyRuntimeConfig
from app.runtime.living_body_runtime import LivingBodyRuntime
from app.runtime.state_driven_body_controller import StateDrivenBodyController

_DIRECTION_POSITIONS: dict[str, tuple[float, float]] = {
    "left": (-0.88, 0.0),
    "right": (0.88, 0.0),
    "up": (0.0, -0.78),
    "down": (0.0, 0.78),
    "up_left": (-0.72, -0.68),
    "up_right": (0.72, -0.68),
    "down_left": (-0.72, 0.68),
    "down_right": (0.72, 0.68),
    "viewer": (0.0, 0.0),
    "speaker": (0.0, 0.0),
    "conversation_partner": (0.0, 0.0),
    "neutral": (0.0, 0.0),
}


def _unit(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


class StateDrivenBodyPoseRuntime(LivingBodyRuntime):
    """ゆらの状態と表現を顔を含む連続BodyPoseFrameへ統合するRuntime。

    `LivingBodyRuntime`のActivity／表現／発話Gatewayと互換AvatarPerformance出力を
    維持しながら、正規の連続出力としてBodyPoseFrameを毎Tick生成する。棒人形、
    Live2D、3D Adapterは同じFrameを受け取り、意味判断や表情選択を行わない。
    """

    def __init__(
        self,
        avatar_output: AvatarOutputPort | None,
        *,
        body_pose_output: BodyPoseFrameOutputPort,
        config: BodyRuntimeConfig | None = None,
        controller: StateDrivenBodyController | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(avatar_output, config=config, **kwargs)
        resolved_config = config or BodyRuntimeConfig()
        self._body_pose_output = body_pose_output
        self._pose_controller = controller or StateDrivenBodyController(
            tick_hz=resolved_config.tick_hz,
        )

    @property
    def pose_controller(self) -> StateDrivenBodyController:
        return self._pose_controller

    async def stop(self) -> None:
        await super().stop()
        close = getattr(self._body_pose_output, "close", None)
        if not callable(close):
            return
        with suppress(Exception):
            result = close()
            if inspect.isawaitable(result):
                await result

    async def update_activity_context(self, context: BodyActivityContext) -> None:
        await super().update_activity_context(context)
        self._pose_controller.set_inner_state(self._inner_state_from_activity(context))
        self._set_activity_attention(context)

    async def request_expression(self, request: BodyExpressionRequest) -> None:
        # 互換AvatarPerformanceと連続Pose Frameの双方へ、同じ意味要求を渡す。
        await super().request_expression(request)
        self._pose_controller.apply_expression(request)
        if request.attention is not None:
            self._set_attention(request.attention)

    async def present_speech(self, request: SpeechPresentationRequest) -> None:
        await super().present_speech(request)
        self._pose_controller.set_speech_active(
            True,
            energy=self._speech_energy(request),
        )

    async def tick_once(self, *, now: float | None = None) -> None:
        current_time = self._monotonic() if now is None else float(now)
        await super().tick_once(now=current_time)

        active_speech = self._active_speech
        self._pose_controller.set_speech_active(
            active_speech is not None,
            energy=(self._speech_energy(active_speech) if active_speech is not None else 0.0),
        )
        frame = self._pose_controller.tick(
            timestamp_ms=max(0, round(current_time * 1000.0)),
            dt_seconds=self._config.tick_interval_seconds,
        )
        try:
            await self._body_pose_output.publish_body_pose_frame(frame)
        except Exception as error:
            await self._record_error(
                f"body_pose_output_failed:{type(error).__name__}:{error}"[:240]
            )

    @staticmethod
    def _inner_state_from_activity(
        context: BodyActivityContext,
    ) -> BodyInnerMotionState:
        posture = context.posture_tendency
        closed = posture in {
            BodyPostureTendency.CLOSED,
            BodyPostureTendency.WITHDRAWN,
        }
        open_posture = posture is BodyPostureTendency.OPEN
        forward = posture is BodyPostureTendency.FORWARD
        withdrawn = posture is BodyPostureTendency.WITHDRAWN
        return BodyInnerMotionState(
            arousal=_unit(0.16 + context.movement_energy * 0.74),
            tension=_unit(0.12 + (0.36 if closed else 0.0)),
            curiosity=_unit(0.16 + context.gaze_freedom * 0.72),
            confidence=_unit(
                0.46
                + (0.22 if open_posture else 0.0)
                + (0.10 if forward else 0.0)
                - (0.24 if closed else 0.0)
            ),
            engagement=context.engagement,
            avoidance=_unit(0.52 if withdrawn else 0.0),
            movement_energy=context.movement_energy,
        )

    def _set_activity_attention(self, context: BodyActivityContext) -> None:
        target = context.attention_target
        if target is None:
            self._pose_controller.set_attention_candidates([])
            return
        self._set_attention(
            BodyAttentionIntent(
                target=target,
                behavior=BodyAttentionBehavior.MAINTAIN,
                engagement=context.engagement,
                eye_follow=1.0,
                head_follow=max(0.2, 0.72 - context.gaze_freedom * 0.34),
                body_follow=max(0.0, 0.28 - context.gaze_freedom * 0.18),
            )
        )

    def _set_attention(self, attention: BodyAttentionIntent) -> None:
        target = attention.target.strip().lower()
        x, y = _DIRECTION_POSITIONS.get(target, (0.0, 0.0))
        if attention.behavior is BodyAttentionBehavior.AVOID:
            if x == 0.0 and y == 0.0:
                x = 0.62
            else:
                x, y = -x, -y
        self._pose_controller.set_attention_candidates(
            [
                BodyAttentionCandidate(
                    candidate_id=target,
                    x=x,
                    y=y,
                    salience=_unit(0.56 + attention.engagement * 0.38),
                    novelty=(
                        0.34
                        if attention.behavior
                        in {BodyAttentionBehavior.GLANCE, BodyAttentionBehavior.SEARCH}
                        else 0.06
                    ),
                    threat=attention.avoidance,
                    relevance=attention.engagement,
                    stability=(
                        0.90
                        if attention.behavior is BodyAttentionBehavior.MAINTAIN
                        else 0.42
                    ),
                )
            ]
        )

    @staticmethod
    def _speech_energy(request: SpeechPresentationRequest) -> float:
        if not request.emphasis:
            return 0.52
        return _unit(0.45 + max(item.strength for item in request.emphasis) * 0.45)
