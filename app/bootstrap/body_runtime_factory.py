from __future__ import annotations

from collections.abc import Callable

from app.bootstrap.body_runtime_settings import BodyRuntimeSettings
from app.domain.body_activity_context import (
    BodyActivityContext,
    BodyPostureTendency,
)
from app.domain.emotions.emotion_state import EmotionState
from app.ports.avatar_output import AvatarOutputPort
from app.ports.body_pose_output import BodyPoseFrameOutputPort
from app.ports.body_subsystem import BodySubsystemPort
from app.runtime.body_expression_input_builder import BodyExpressionInputBuilder
from app.runtime.body_runtime import BodyRuntime, BodyRuntimeConfig
from app.runtime.state_driven_body_controller import StateDrivenBodyController
from app.runtime.state_driven_body_pose_runtime import StateDrivenBodyPoseRuntime


class BodyRuntimeFactory:
    """型付き設定とPortから利用するBody Runtime実装を選択する。"""

    def create(
        self,
        *,
        settings: BodyRuntimeSettings,
        avatar_output: AvatarOutputPort | None,
        pose_output: BodyPoseFrameOutputPort | None,
        emotion_provider: Callable[[], EmotionState],
    ) -> BodySubsystemPort | None:
        if not isinstance(settings, BodyRuntimeSettings):
            raise TypeError("settings must be BodyRuntimeSettings")
        if not settings.enabled:
            return None
        if not callable(emotion_provider):
            raise TypeError("emotion_provider must be callable")

        if pose_output is not None:
            return self._create_continuous_pose_runtime(
                settings=settings,
                pose_output=pose_output,
                emotion_provider=emotion_provider,
            )
        if avatar_output is not None:
            return self._create_compatibility_runtime(
                settings=settings,
                avatar_output=avatar_output,
            )
        return None

    @staticmethod
    def _create_continuous_pose_runtime(
        *,
        settings: BodyRuntimeSettings,
        pose_output: BodyPoseFrameOutputPort,
        emotion_provider: Callable[[], EmotionState],
    ) -> StateDrivenBodyPoseRuntime:
        context = BodyActivityContext(
            source_activity_id="body-runtime-idle",
            attention_target=None,
            engagement=0.25,
            posture_tendency=BodyPostureTendency.NEUTRAL,
            movement_energy=0.22,
            gaze_freedom=0.82,
        )
        input_builder = BodyExpressionInputBuilder()
        initial_input = input_builder.build(
            emotion=emotion_provider(),
            context=context,
        )
        controller = StateDrivenBodyController(
            initial_input,
            tick_hz=settings.tick_hz,
            seed=settings.random_seed,
        )
        return StateDrivenBodyPoseRuntime(
            controller=controller,
            output=pose_output,
            emotion_provider=emotion_provider,
            initial_context=context,
            input_builder=input_builder,
        )

    @staticmethod
    def _create_compatibility_runtime(
        *,
        settings: BodyRuntimeSettings,
        avatar_output: AvatarOutputPort,
    ) -> BodyRuntime:
        return BodyRuntime(
            avatar_output,
            config=BodyRuntimeConfig(
                tick_hz=settings.tick_hz,
                expression_queue_limit=settings.expression_queue_limit,
                max_expressions_per_tick=settings.max_expressions_per_tick,
                autonomous_interval_ms=settings.autonomous_interval_ms,
                baseline_refresh_ms=settings.baseline_refresh_ms,
            ),
        )
