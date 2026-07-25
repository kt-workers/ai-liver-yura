from __future__ import annotations

from datetime import datetime

from app.domain.topic import InterruptedTopic
from app.runtime.agent_life_service import AgentLifeService
from app.runtime.autonomous_topic_tracker import AutonomousTopicTracker


class TopicTrackingAgentLifeService(AgentLifeService):
    """話題固有処理を``AutonomousTopicTracker``へ委譲する移行用Facade。

    ``AgentLifeService``の公開APIを変更せず、話題状態の生成・更新・終了判定を
    専用コンポーネントへ移す。基底クラス内に残る既存処理との互換性を保つため、
    委譲の前後で従来の内部状態へ同期する。
    """

    def __init__(
        self,
        *args: object,
        autonomous_topic_tracker: AutonomousTopicTracker | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._autonomous_topic_tracker = (
            autonomous_topic_tracker or AutonomousTopicTracker()
        )
        self._sync_tracker_from_legacy_state()

    @classmethod
    def from_existing(
        cls,
        service: AgentLifeService,
        *,
        autonomous_topic_tracker: AutonomousTopicTracker | None = None,
    ) -> TopicTrackingAgentLifeService:
        """既存Serviceの状態を保持したまま委譲型へ移行する。"""

        if isinstance(service, cls):
            return service
        upgraded = cls.__new__(cls)
        upgraded.__dict__ = service.__dict__.copy()
        upgraded._autonomous_topic_tracker = (
            autonomous_topic_tracker or AutonomousTopicTracker()
        )
        upgraded._sync_tracker_from_legacy_state()
        return upgraded

    @property
    def autonomous_topic(self) -> InterruptedTopic | None:
        self._sync_tracker_from_legacy_state()
        return self._autonomous_topic_tracker.current_topic

    def record_autonomous_output(
        self,
        *,
        activity_id: str,
        text: str,
        context: dict[str, object] | None = None,
    ) -> InterruptedTopic:
        self._sync_tracker_from_legacy_state()
        topic = self._autonomous_topic_tracker.record_output(
            activity_id=activity_id,
            text=text,
            drive=self.agent_state.current_drive,
            emotion=self.agent_state.current_emotion,
            context=context,
        )
        self._sync_legacy_state_from_tracker()
        self._trace_logger.info(
            "agent_life_service:autonomous_topic:recorded",
            topic_id=topic.topic_id,
            source_activity_id=topic.source_activity_id,
            topic_status=topic.status.value,
            importance=topic.importance,
            interest=topic.interest,
            incompleteness=topic.incompleteness,
            exhaustion=topic.exhaustion,
            turn_count=topic.turn_count,
        )
        return topic

    def should_complete_autonomous_activity(self, *, activity_id: str) -> bool:
        self._sync_tracker_from_legacy_state()
        should_complete, continuation_strength = (
            self._autonomous_topic_tracker.should_complete(
                activity_id=activity_id,
                drive=self.agent_state.current_drive,
                emotion=self.agent_state.current_emotion,
            )
        )
        topic = self._autonomous_topic_tracker.current_topic
        if topic is None or continuation_strength is None:
            return False
        emotion = self.agent_state.current_emotion
        drive = self.agent_state.current_drive
        self._trace_logger.info(
            "agent_life_service:autonomous_topic:continuation_evaluated",
            topic_id=topic.topic_id,
            source_activity_id=activity_id,
            turn_count=topic.turn_count,
            interest=topic.interest,
            incompleteness=topic.incompleteness,
            exhaustion=topic.exhaustion,
            emotion_arousal=emotion.arousal,
            emotion_talkativeness=emotion.talkativeness,
            drive_curiosity=drive.curiosity,
            continuation_strength=continuation_strength,
            should_complete=should_complete,
        )
        return should_complete

    def interrupt_autonomous_topic(
        self,
        *,
        activity_id: str,
        fallback_text: str,
        now: datetime | None = None,
    ) -> InterruptedTopic:
        self._sync_tracker_from_legacy_state()
        interrupted = self._autonomous_topic_tracker.interrupt(
            activity_id=activity_id,
            fallback_text=fallback_text,
            now=now,
        )
        self._sync_legacy_state_from_tracker()
        self._trace_logger.info(
            "agent_life_service:autonomous_topic:interrupted",
            topic_id=interrupted.topic_id,
            source_activity_id=activity_id,
            topic_status=interrupted.status.value,
        )
        return interrupted

    def complete_autonomous_topic(self, *, activity_id: str) -> None:
        self._sync_tracker_from_legacy_state()
        self._autonomous_topic_tracker.complete(activity_id=activity_id)
        self._sync_legacy_state_from_tracker()

    def _sync_tracker_from_legacy_state(self) -> None:
        self._autonomous_topic_tracker.replace(self._autonomous_topic)

    def _sync_legacy_state_from_tracker(self) -> None:
        self._autonomous_topic = self._autonomous_topic_tracker.current_topic
        self._recent_autonomous_texts = list(
            self._autonomous_topic_tracker.recent_autonomous_texts
        )
