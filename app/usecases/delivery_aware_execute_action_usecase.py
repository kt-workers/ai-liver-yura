from __future__ import annotations

from app.domain.actions import ActionPlan
from app.usecases.execute_action_usecase import (
    ExecuteActionUsecase as BaseExecuteActionUsecase,
)


class ExecuteActionUsecase(BaseExecuteActionUsecase):
    """Coreのテキスト発話成立を任意の音声出力から分離する。"""

    async def _play_speech(self, action_plan: ActionPlan) -> str | None:
        """VOICEVOX等の失敗を観測しつつCoreのSPEAK成功を維持する。

        このメソッドが呼ばれる時点では、基底UseCaseによって会話出力Publisher、
        コンソール表示、Short Term Memoryへのコミットが完了している。
        そのため音声チャネルの失敗は発話自体の失敗ではなく、任意出力の縮退として扱う。
        """

        playback_error = await super()._play_speech(action_plan)
        if playback_error is None:
            return None

        self._trace_logger.warning(
            "execute_action_usecase:speak:optional_voice_output_degraded",
            action_id=action_plan.action_id,
            source_activity_id=action_plan.source_activity_id,
            reason="text_output_already_committed",
            audio_error=playback_error,
        )
        self._trace_logger.info(
            "execute_action_usecase:speak:topic_memory_allowed_after_audio_failure",
            action_id=action_plan.action_id,
            source_activity_id=action_plan.source_activity_id,
            reason="text_output_committed",
        )
        return None
