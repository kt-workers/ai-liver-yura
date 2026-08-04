from __future__ import annotations

from typing import Any

from app.domain.actions import ActionPlan, ActionType
from app.domain.activity_turn_result import ActionExecutionResult
from app.plugins.avatar_output import AvatarOutputPlugin
from app.plugins.avatar_output.runtime import create_avatar_output_plugin_from_env
from app.usecases.execute_action_usecase import (
    ExecuteActionUsecase as CoreExecuteActionUsecase,
)
from app.utils.trace import TraceLogger


class ExecuteActionUsecase(CoreExecuteActionUsecase):
    """既存Action実行へ交換可能なAvatar Output Pluginを合成する。"""

    def __init__(
        self,
        *args: Any,
        avatar_output_plugin: AvatarOutputPlugin | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._avatar_output_plugin = (
            avatar_output_plugin
            if avatar_output_plugin is not None
            else create_avatar_output_plugin_from_env()
        )
        self._avatar_trace_logger = TraceLogger()

    async def execute(self, action_plan: ActionPlan) -> ActionExecutionResult | None:
        plugin = self._avatar_output_plugin
        if plugin is None or action_plan.action_type not in {
            ActionType.CHANGE_EXPRESSION,
            ActionType.MOVE,
        }:
            return await super().execute(action_plan)

        try:
            if action_plan.action_type == ActionType.CHANGE_EXPRESSION:
                await plugin.set_expression(action_plan.text)
            else:
                await plugin.play_gesture(action_plan.text)
        except Exception as error:
            # Avatar出力は任意Capabilityであり、描画停止時もCoreを継続する。
            self._avatar_trace_logger.warning(
                "execute_action_usecase:avatar_output_failed",
                action_id=action_plan.action_id,
                action_type=action_plan.action_type.value,
                source_activity_id=action_plan.source_activity_id,
                output_unit_id=action_plan.output_unit_id,
                error_type=type(error).__name__,
                error_message=str(error),
            )
            return None

        self._avatar_trace_logger.write(
            "execute_action_usecase:avatar_output_finished",
            action_id=action_plan.action_id,
            action_type=action_plan.action_type.value,
            source_activity_id=action_plan.source_activity_id,
            output_unit_id=action_plan.output_unit_id,
            avatar_command=action_plan.text,
        )
        return None
