from __future__ import annotations

from collections import deque
from typing import Any

from app.domain.actions import ActionPlan, ActionType
from app.domain.activity_turn_result import ActionExecutionResult
from app.domain.avatar_performance import AvatarPerformancePlan
from app.ports.avatar_output import AvatarOutputPort, get_bound_avatar_output
from app.usecases.delivery_aware_execute_action_usecase import (
    ExecuteActionUsecase as DeliveryAwareExecuteActionUsecase,
)
from app.utils.trace import TraceLogger


class ExecuteActionUsecase(DeliveryAwareExecuteActionUsecase):
    """既存Action実行へ交換可能なAvatar Output Portを合成する。"""

    _MAX_TRACKED_PERFORMANCES = 256

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
        self._submitted_performance_ids: set[str] = set()
        self._submitted_performance_order: deque[str] = deque()

    async def execute(self, action_plan: ActionPlan) -> ActionExecutionResult | None:
        avatar_output = self._avatar_output
        if avatar_output is None or action_plan.action_type not in {
            ActionType.CHANGE_EXPRESSION,
            ActionType.MOVE,
        }:
            return await super().execute(action_plan)

        performance_id = action_plan.metadata.get("avatar_performance_id")
        performance = action_plan.metadata.get("avatar_performance_plan")
        performance_managed = (
            action_plan.metadata.get("avatar_performance_managed") is True
            and isinstance(performance_id, str)
            and bool(performance_id.strip())
        )

        if performance_managed and performance_id in self._submitted_performance_ids:
            self._avatar_trace_logger.write(
                "execute_action_usecase:avatar_individual_action_skipped",
                action_id=action_plan.action_id,
                action_type=action_plan.action_type.value,
                performance_id=performance_id,
                reason="performance_already_submitted",
            )
            return None

        if performance_managed and isinstance(performance, AvatarPerformancePlan):
            submit_performance = getattr(avatar_output, "submit_performance", None)
            if callable(submit_performance):
                try:
                    await submit_performance(performance)
                except Exception as error:
                    # Performance API障害時は既存の個別Actionへ縮退する。
                    self._avatar_trace_logger.warning(
                        "execute_action_usecase:avatar_performance_failed",
                        action_id=action_plan.action_id,
                        source_activity_id=action_plan.source_activity_id,
                        output_unit_id=action_plan.output_unit_id,
                        performance_id=performance.performance_id,
                        error_type=type(error).__name__,
                        error_message=str(error),
                    )
                else:
                    self._remember_submitted_performance(performance.performance_id)
                    self._avatar_trace_logger.write(
                        "execute_action_usecase:avatar_performance_submitted",
                        action_id=action_plan.action_id,
                        source_activity_id=action_plan.source_activity_id,
                        output_unit_id=action_plan.output_unit_id,
                        performance_id=performance.performance_id,
                        segment_count=len(performance.segments),
                    )
                    return None

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

    def _remember_submitted_performance(self, performance_id: str) -> None:
        if performance_id in self._submitted_performance_ids:
            return
        if len(self._submitted_performance_order) >= self._MAX_TRACKED_PERFORMANCES:
            discarded = self._submitted_performance_order.popleft()
            self._submitted_performance_ids.discard(discarded)
        self._submitted_performance_order.append(performance_id)
        self._submitted_performance_ids.add(performance_id)
