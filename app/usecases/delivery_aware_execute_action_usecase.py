from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone

from app.domain.actions import ActionPlan, ActionType
from app.domain.activity_turn_result import ActionExecutionResult, ActionExecutionStatus
from app.domain.output_delivery import optional_output_degraded_error
from app.usecases.execute_action_usecase import (
    ExecuteActionUsecase as BaseExecuteActionUsecase,
)


class ExecuteActionUsecase(BaseExecuteActionUsecase):
    """Coreのテキスト発話成立を任意の音声出力から分離する。"""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._voice_errors_after_text_commit: dict[str, str] = {}

    def _can_persist_topic_memory(self, action_plan: ActionPlan) -> bool:
        return (
            action_plan.metadata.get("skip_topic_memory") is not True
            and self._topic_history is not None
            and self._topic_classifier is not None
            and self._embedding_generator is not None
            and self._topic_memory_store is not None
        )

    async def _play_speech(self, action_plan: ActionPlan) -> str | None:
        """音声縮退を記録し、DB構成済みなら記憶処理を継続する。"""

        playback_error = await super()._play_speech(action_plan)
        if playback_error is None:
            return None

        degraded_error = optional_output_degraded_error("voice", playback_error)
        self._voice_errors_after_text_commit[action_plan.action_id] = degraded_error
        self._trace_logger.warning(
            "execute_action_usecase:speak:optional_voice_output_degraded",
            action_id=action_plan.action_id,
            source_activity_id=action_plan.source_activity_id,
            reason="text_output_already_committed",
            audio_error=playback_error,
        )
        if not self._can_persist_topic_memory(action_plan):
            return degraded_error

        self._trace_logger.info(
            "execute_action_usecase:speak:topic_memory_allowed_after_audio_failure",
            action_id=action_plan.action_id,
            source_activity_id=action_plan.source_activity_id,
            reason="text_output_committed",
        )
        return None

    async def execute(self, action_plan: ActionPlan) -> ActionExecutionResult | None:
        if action_plan.action_type != ActionType.SPEAK:
            return await super().execute(action_plan)

        original_pause = action_plan.metadata.get("pause_after_seconds", 0.0)
        execution_plan = replace(
            action_plan,
            metadata={**action_plan.metadata, "pause_after_seconds": 0.0},
        )
        result = await super().execute(execution_plan)
        degraded_error = self._voice_errors_after_text_commit.pop(
            action_plan.action_id, None
        )
        if degraded_error is None:
            if (
                result is None
                and isinstance(original_pause, (int, float))
                and not isinstance(original_pause, bool)
                and original_pause > 0
            ):
                await asyncio.sleep(min(float(original_pause), 3.0))
            return result

        now = datetime.now(timezone.utc)
        return ActionExecutionResult(
            action_id=action_plan.action_id,
            action_type=action_plan.action_type.value,
            status=ActionExecutionStatus.FAILED,
            output_unit_id=action_plan.output_unit_id or "",
            activity_turn_id="",
            error=degraded_error,
            started_at=now,
            finished_at=now,
        )
