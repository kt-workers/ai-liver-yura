from __future__ import annotations

from collections import deque
from typing import Any

from app.domain.actions import ActionPlan
from app.domain.body import BodyActivityContext
from app.domain.body_motion import BodyMotionRequest
from app.usecases.avatar_aware_execute_action_usecase import (
    ExecuteActionUsecase as AvatarAwareExecuteActionUsecase,
)


class ExecuteActionUsecase(AvatarAwareExecuteActionUsecase):
    """既存Action実行にCore BodyMotionRequest配送を追加する。"""

    _MAX_TRACKED_MOTIONS = 256

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._submitted_motion_ids: set[str] = set()
        self._submitted_motion_order: deque[str] = deque()

    async def execute(self, action_plan: ActionPlan):  # type: ignore[no-untyped-def]
        motion_request = action_plan.metadata.get("body_motion_request")
        if isinstance(motion_request, BodyMotionRequest):
            await self._submit_motion_request(action_plan, motion_request)
        return await super().execute(action_plan)

    async def _submit_motion_request(
        self,
        action_plan: ActionPlan,
        request: BodyMotionRequest,
    ) -> bool:
        motion_id = request.motion_id or action_plan.action_id
        if motion_id in self._submitted_motion_ids:
            return True
        body = self._body()
        if body is None:
            return False
        context = action_plan.metadata.get("body_activity_context")
        try:
            if isinstance(context, BodyActivityContext):
                await body.update_activity_context(context)
            await body.request_motion(request)
        except Exception as error:
            self._avatar_trace_logger.warning(
                "execute_action_usecase:body_motion_failed",
                action_id=action_plan.action_id,
                source_activity_id=action_plan.source_activity_id,
                output_unit_id=action_plan.output_unit_id,
                motion_id=motion_id,
                operation=request.operation.value,
                error_type=type(error).__name__,
                error_message=str(error),
            )
            return False
        self._remember_bounded(
            motion_id,
            values=self._submitted_motion_ids,
            order=self._submitted_motion_order,
            limit=self._MAX_TRACKED_MOTIONS,
        )
        self._avatar_trace_logger.write(
            "execute_action_usecase:body_motion_submitted",
            action_id=action_plan.action_id,
            source_activity_id=action_plan.source_activity_id,
            output_unit_id=action_plan.output_unit_id,
            motion_id=motion_id,
            operation=request.operation.value,
        )
        return True
