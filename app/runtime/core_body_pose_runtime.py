from __future__ import annotations

import inspect
from collections import deque
from contextlib import suppress

from app.domain.body import (
    BodyActivityContext,
    BodyAttentionBehavior,
    BodyAttentionIntent,
    BodyExpressionRequest,
    BodyPostureTendency,
)
from app.domain.body_pose_frame import (
    BodyAttentionCandidate,
    BodyInnerMotionState,
)
from app.domain.body_speech import SpeechCoupledBodyExpressionRequest
from app.ports.avatar_output import AvatarOutputPort
from app.ports.body_pose_output import BodyPoseFrameOutputPort
from app.runtime.body_pose_3d_projector import KinematicProceduralBodyController
from app.runtime.body_runtime import BodyRuntimeConfig
from app.runtime.living_body_runtime import LivingBodyRuntime

_DIRECTION_POSITIONS: dict[str, tuple[float, float]] = {
    "left": (-0.88, 0.0),
    "right": (0.88, 0.0),
    "up": (0.0, -0.78),
    "down": (0.0, 0.78),
    "up_left": (-0.72, -0.68),
    "up_right": (0.72, -0.68),
    "down_left": (-0.72, 0.68),
    "down_right": (0.72, 0.68),
    "center": (0.0, 0.0),
    "viewer": (0.0, 0.0),
}
_SUPPORTED_BODY_COMMANDS = {
    "right_hand_raise",
    "left_hand_raise",
    "both_hands_raise",
    "right_hand_wave",
    "left_hand_wave",
    "both_hands_wave",
    "eyes_close",
    "eyes_open",
    "blink",
    "mouth_open",
    "mouth_close",
    "head_circle",
    "bow",
    "jump",
    "body_sway",
    "body_twist",
}


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _body_command_duration(duration_ms: int | None) -> int | None:
    if duration_ms is None:
        return None
    return max(200, min(10_000, duration_ms))


class CoreBodyPoseRuntime(LivingBodyRuntime):
    """Coreの意味状態を連続BodyPoseFrameへ変換してAvatar Mockへ送る。

    高レベルのAvatarPerformancePlan経路は互換のため残しつつ、棒人間・Live2D・
    将来の別Avatar Adapterが共通利用できるBodyPoseFrameを毎Tick生成する。
    """

    def __init__(
        self,
        avatar_output: AvatarOutputPort | None,
        *,
        body_pose_output: BodyPoseFrameOutputPort,
        config: BodyRuntimeConfig | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(avatar_output, config=config, **kwargs)
        resolved_config = config or BodyRuntimeConfig()
        self._body_pose_output = body_pose_output
        self._pose_controller = KinematicProceduralBodyController(
            tick_hz=resolved_config.tick_hz,
        )
        self._base_inner_state = BodyInnerMotionState()
        self._expression_inner_state: BodyInnerMotionState | None = None
        self._expression_state_until: float | None = None
        self._pending_body_commands: deque[tuple[str, int | None]] = deque()

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
        self._base_inner_state = self._inner_state_from_activity(context)
        self._pose_controller.set_inner_state(self._base_inner_state)
        self._set_attention_from_activity(context)

    async def request_expression(self, request: BodyExpressionRequest) -> None:
        await super().request_expression(request)
        self._expression_inner_state = self._inner_state_from_expression(request)
        duration_ms = request.duration_hint_ms or 1800
        self._expression_state_until = self._monotonic() + duration_ms / 1000.0
        if request.attention is not None:
            self._set_attention(request.attention)
        if isinstance(request, SpeechCoupledBodyExpressionRequest):
            command_duration = _body_command_duration(request.duration_hint_ms)
            for command in request.body_actions:
                if command in _SUPPORTED_BODY_COMMANDS:
                    self._pending_body_commands.append((command, command_duration))

    async def tick_once(self, *, now: float | None = None) -> None:
        current_time = self._monotonic() if now is None else float(now)
        await super().tick_once(now=current_time)
        self._refresh_controller_state(current_time)
        if (
            self._pose_controller.active_body_command is None
            and self._pending_body_commands
        ):
            command, duration_ms = self._pending_body_commands.popleft()
            self._pose_controller.apply_body_command(
                command,
                duration_ms=duration_ms,
            )
        frame = self._pose_controller.tick(
            timestamp_ms=max(0, round(current_time * 1000.0)),
            dt_seconds=self._config.tick_interval_seconds,
        )
        await self._body_pose_output.publish_body_pose_frame(frame)

    def _refresh_controller_state(self, now: float) -> None:
        if (
            self._expression_inner_state is not None
            and self._expression_state_until is not None
            and now < self._expression_state_until
        ):
            self._pose_controller.set_inner_state(self._expression_inner_state)
            return
        self._expression_inner_state = None
        self._expression_state_until = None
        self._pose_controller.set_inner_state(self._base_inner_state)

    @staticmethod
    def _inner_state_from_activity(
        context: BodyActivityContext,
    ) -> BodyInnerMotionState:
        posture = context.posture_tendency
        closed = posture in {
            BodyPostureTendency.CLOSED,
            BodyPostureTendency.WITHDRAWN,
        }
        forward = posture is BodyPostureTendency.FORWARD
        open_posture = posture is BodyPostureTendency.OPEN
        return BodyInnerMotionState(
            arousal=_clamp(0.18 + context.movement_energy * 0.72),
            tension=_clamp(0.12 + (0.38 if closed else 0.0)),
            curiosity=_clamp(0.18 + context.gaze_freedom * 0.72),
            confidence=_clamp(
                0.46
                + (0.22 if open_posture else 0.0)
                + (0.10 if forward else 0.0)
                - (0.24 if closed else 0.0)
            ),
            engagement=context.engagement,
            avoidance=_clamp(
                0.46
                if posture is BodyPostureTendency.WITHDRAWN
                else 0.0
            ),
            movement_energy=context.movement_energy,
        )

    def _inner_state_from_expression(
        self,
        request: BodyExpressionRequest,
    ) -> BodyInnerMotionState:
        expression = request.expression
        base = self._base_inner_state
        return BodyInnerMotionState(
            arousal=max(base.arousal, expression.arousal),
            tension=max(base.tension, expression.tension),
            curiosity=base.curiosity,
            confidence=_clamp(
                base.confidence
                + expression.assertiveness * 0.28
                + expression.valence * 0.14
            ),
            engagement=_clamp(
                max(
                    base.engagement,
                    expression.warmth * 0.52
                    + abs(expression.approach) * 0.32,
                )
            ),
            avoidance=_clamp(
                max(base.avoidance, max(0.0, -expression.approach) * 0.86)
            ),
            movement_energy=_clamp(
                max(
                    base.movement_energy,
                    expression.intensity * 0.54 + expression.arousal * 0.46,
                )
            ),
        )

    def _set_attention_from_activity(self, context: BodyActivityContext) -> None:
        target = context.attention_target
        if target is None:
            self._pose_controller.set_attention_candidates([])
            return
        self._set_attention(
            BodyAttentionIntent(
                target=target,
                engagement=context.engagement,
                eye_follow=1.0,
                head_follow=0.62,
                body_follow=0.18,
            )
        )

    def _set_attention(self, attention: BodyAttentionIntent) -> None:
        target = attention.target.strip().lower()
        x, y = _DIRECTION_POSITIONS.get(target, (0.0, 0.0))
        if attention.behavior is BodyAttentionBehavior.AVOID:
            x, y = -x, -y
        self._pose_controller.set_attention_candidates(
            [
                BodyAttentionCandidate(
                    candidate_id=target,
                    x=x,
                    y=y,
                    salience=_clamp(0.58 + attention.engagement * 0.36),
                    novelty=0.08,
                    threat=attention.avoidance,
                    relevance=attention.engagement,
                    stability=_clamp(
                        0.82
                        if attention.behavior is BodyAttentionBehavior.MAINTAIN
                        else 0.42
                    ),
                )
            ]
        )
