from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone

from app.domain.actions import ActionPlan, ActionType
from app.domain.activity_turn_result import ActionExecutionResult, ActionExecutionStatus
from app.domain.short_term_memory import ShortTermMemory
from app.domain.topic import TopicHistory
from app.domain.topic_classifier import TopicClassifier
from app.ports.audio_player import AudioPlayer
from app.ports.conversation_output import ConversationOutputPublisher
from app.ports.embedding_generator import EmbeddingGenerator
from app.ports.event_publisher import EventPublisher
from app.ports.memory_summary_generator import MemorySummaryGenerator
from app.ports.speech_synthesizer import SpeechSynthesizer
from app.ports.topic_memory_store import TopicMemoryStore
from app.usecases.execute_action_usecase import (
    ExecuteActionUsecase as BaseExecuteActionUsecase,
)
from app.utils.conversation_log import ConversationLogger


class ExecuteActionUsecase(BaseExecuteActionUsecase):
    """テキスト出力済みの発話記憶を音声結果から独立して保存する。"""

    def __init__(
        self,
        event_publisher: EventPublisher | None = None,
        short_term_memory: ShortTermMemory | None = None,
        topic_history: TopicHistory | None = None,
        topic_classifier: TopicClassifier | None = None,
        embedding_generator: EmbeddingGenerator | None = None,
        topic_memory_store: TopicMemoryStore | None = None,
        memory_summary_generator: MemorySummaryGenerator | None = None,
        speech_synthesizer: SpeechSynthesizer | None = None,
        audio_player: AudioPlayer | None = None,
        background_topic_memory: bool = False,
        conversation_logger: ConversationLogger | None = None,
        conversation_output_publisher: ConversationOutputPublisher | None = None,
    ) -> None:
        super().__init__(
            event_publisher=event_publisher,
            short_term_memory=short_term_memory,
            topic_history=topic_history,
            topic_classifier=topic_classifier,
            embedding_generator=embedding_generator,
            topic_memory_store=topic_memory_store,
            memory_summary_generator=memory_summary_generator,
            speech_synthesizer=speech_synthesizer,
            audio_player=audio_player,
            background_topic_memory=background_topic_memory,
            conversation_logger=conversation_logger,
            conversation_output_publisher=conversation_output_publisher,
        )
        self._audio_errors_after_text_commit: dict[str, str] = {}

    def _can_persist_topic_memory(self, action_plan: ActionPlan) -> bool:
        return (
            action_plan.metadata.get("skip_topic_memory") is not True
            and self._topic_history is not None
            and self._topic_classifier is not None
            and self._embedding_generator is not None
            and self._topic_memory_store is not None
        )

    async def _play_speech(self, action_plan: ActionPlan) -> str | None:
        playback_error = await super()._play_speech(action_plan)
        if playback_error is None or not self._can_persist_topic_memory(action_plan):
            return playback_error

        self._audio_errors_after_text_commit[action_plan.action_id] = playback_error
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
        playback_error = self._audio_errors_after_text_commit.pop(
            action_plan.action_id, None
        )

        if playback_error is None:
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
            error=playback_error,
            started_at=now,
            finished_at=now,
        )
