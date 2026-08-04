from __future__ import annotations

from typing import Any

from app.domain.actions import ActionPlan, ActionType
from app.domain.activity_turn_result import ActionExecutionResult
from app.ports.avatar_output import AvatarOutputPort, get_bound_avatar_output
from app.usecases.delivery_aware_execute_action_usecase import (
    ExecuteActionUsecase as DeliveryAwareExecuteActionUsecase,
)
from app.utils.trace import TraceLogger


class ExecuteActionUsecase(DeliveryAwareExecuteActionUsecase):
    """既存Action実行へ交換可能なAvatar Output Portを合成する。"""

    def __init__(
        self,
        *args: Any,
        avatar_output: AvatarOutputPort | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._avatar_output = (
            avatar_output
            if avatar_output is not None
            else get_bound_avatar_output()
        )
        self._avatar_trace_logger = TraceLogger()

    async def execute(self, action_plan: ActionPlan) -> ActionExecutionResult | None:
        avatar_output = self._avatar_output
        if avatar_output is None or action_plan.action_type not in {
            ActionType.CHANGE_EXPRESSION,
            ActionType.MOVE,
        }:
            return await super().execute(action_plan)

        try:
            if action_plan.action_type == ActionType.CHANGE_EXPRESSION:
                await avatar_output.set_expression(action_plan.text)
            else:
                await avatar_output.play_gesture(action_plan.text)
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
