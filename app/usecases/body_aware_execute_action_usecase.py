from __future__ import annotations

from typing import Any

from app.domain.actions import ActionPlan, ActionType
from app.domain.activity_turn_result import ActionExecutionResult
from app.domain.body_instruction import BodyInstruction
from app.runtime.body_instruction_executor import BodyInstructionExecutor
from app.usecases.execute_action_usecase import ExecuteActionUsecase
from app.utils.trace import TraceLogger


class BodyAwareExecuteActionUsecase(ExecuteActionUsecase):
    """通常Action実行へ、明示Body指示の同期MOVEだけを追加する。"""

    def __init__(
        self,
        *args: Any,
        body_instruction_executor: BodyInstructionExecutor | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._body_instruction_executor = (
            body_instruction_executor or BodyInstructionExecutor()
        )
        self._body_trace = TraceLogger()

    async def execute(
        self,
        action_plan: ActionPlan,
    ) -> ActionExecutionResult | None:
        if (
            action_plan.action_type is ActionType.MOVE
            and action_plan.metadata.get("body_instruction_execution") is True
        ):
            instruction = BodyInstruction.from_context(
                action_plan.metadata.get("explicit_body_instruction")
            )
            if instruction is None:
                raise RuntimeError("explicit_body_instruction_missing")
            result = await self._body_instruction_executor.execute(instruction)
            self._body_trace.info(
                "body_action_output:explicit_instruction_executed",
                action_id=action_plan.action_id,
                source_activity_id=action_plan.source_activity_id,
                output_unit_id=action_plan.output_unit_id,
                execution_status=result.status.value,
                result_reason=result.reason,
                target_axes=list(result.target_axes),
            )
            if not result.applied:
                raise RuntimeError(
                    "body_constraint_not_applied:"
                    f"{result.status.value}:{result.reason}"
                )
            return None
        return await super().execute(action_plan)


__all__ = ["BodyAwareExecuteActionUsecase"]
