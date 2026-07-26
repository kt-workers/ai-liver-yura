from __future__ import annotations

from pathlib import Path


AGENT = Path("app/runtime/agent_life_service.py")
FACADE = Path("app/runtime/topic_tracking_agent_life_service.py")
BOOTSTRAP = Path("app/bootstrap/emotion_runtime.py")
TEST = Path("tests/test_topic_tracking_agent_life_service.py")


def replace_once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"置換対象の出現数が不正です: expected=1 actual={count}\n{old}")
    return text.replace(old, new, 1)


def update_agent() -> None:
    text = AGENT.read_text(encoding="utf-8")
    if "autonomous_topic_tracker: AutonomousTopicTracker | None" in text:
        return

    text = text.replace("from difflib import SequenceMatcher\n", "")
    text = text.replace("from uuid import uuid4\n", "")
    text = replace_once(
        text,
        "from app.runtime.autonomous_plan_state import AutonomousPlanState\n",
        "from app.runtime.autonomous_plan_state import AutonomousPlanState\n"
        "from app.runtime.autonomous_topic_tracker import AutonomousTopicTracker\n",
    )
    text = replace_once(
        text,
        "        autonomous_event_planner: AutonomousEventPlanner | None = None,\n"
        "        state_observer: Callable[[AgentState], None] | None = None,\n",
        "        autonomous_event_planner: AutonomousEventPlanner | None = None,\n"
        "        autonomous_topic_tracker: AutonomousTopicTracker | None = None,\n"
        "        state_observer: Callable[[AgentState], None] | None = None,\n",
    )
    text = replace_once(
        text,
        "        self._autonomous_topic: InterruptedTopic | None = None\n"
        "        self._recent_autonomous_texts: list[str] = []\n",
        "        self._autonomous_topic_tracker = (\n"
        "            autonomous_topic_tracker or AutonomousTopicTracker()\n"
        "        )\n",
    )
    text = replace_once(
        text,
        "    @property\n"
        "    def autonomous_topic(self) -> InterruptedTopic | None:\n"
        "        return self._autonomous_topic\n",
        "    @property\n"
        "    def autonomous_topic(self) -> InterruptedTopic | None:\n"
        "        return self._autonomous_topic_tracker.current_topic\n",
    )

    method_start = text.index("    def record_autonomous_output(")
    method_end = text.index("    def plan_next_event(", method_start)
    replacement = '''    def record_autonomous_output(
        self,
        *,
        activity_id: str,
        text: str,
        context: dict[str, object] | None = None,
    ) -> InterruptedTopic:
        """出力成功済みの自律発話を、再開判断可能な話題状態として保持する。"""

        topic = self._autonomous_topic_tracker.record_output(
            activity_id=activity_id,
            text=text,
            drive=self._agent_state.current_drive,
            emotion=self._agent_state.current_emotion,
            context=context,
        )
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
        """感情・動機と、話題の減衰状態から発話Activityの自然終了を判断する。"""

        should_complete, continuation_strength = (
            self._autonomous_topic_tracker.should_complete(
                activity_id=activity_id,
                drive=self._agent_state.current_drive,
                emotion=self._agent_state.current_emotion,
            )
        )
        topic = self._autonomous_topic_tracker.current_topic
        if topic is None or continuation_strength is None:
            return False
        emotion = self._agent_state.current_emotion
        drive = self._agent_state.current_drive
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
        interrupted = self._autonomous_topic_tracker.interrupt(
            activity_id=activity_id,
            fallback_text=fallback_text,
            now=now,
        )
        self._trace_logger.info(
            "agent_life_service:autonomous_topic:interrupted",
            topic_id=interrupted.topic_id,
            source_activity_id=activity_id,
            topic_status=interrupted.status.value,
        )
        return interrupted

    def complete_autonomous_topic(self, *, activity_id: str) -> None:
        self._autonomous_topic_tracker.complete(activity_id=activity_id)

'''
    text = text[:method_start] + replacement + text[method_end:]
    text = text.replace(
        "            autonomous_topic_provider=lambda: self._autonomous_topic,\n",
        "            autonomous_topic_provider=lambda: self.autonomous_topic,\n",
    )
    text = replace_once(
        text,
        "            if self._autonomous_topic is not None and isinstance(text, str):\n"
        "                self._autonomous_topic = self._autonomous_topic.add_interruption_topic(\n"
        "                    text\n"
        "                )\n",
        "            if isinstance(text, str):\n"
        "                self._autonomous_topic_tracker.add_interruption_topic(text)\n",
    )
    text = text.replace(
        "            autonomous_topic=self._autonomous_topic,\n",
        "            autonomous_topic=self.autonomous_topic,\n",
    )
    text = replace_once(
        text,
        "        topic = self._autonomous_topic\n",
        "        topic = self._autonomous_topic_tracker.current_topic\n",
    )
    text = replace_once(
        text,
        "        self._autonomous_topic = topic.with_status(next_status)\n",
        "        self._autonomous_topic_tracker.replace(topic.with_status(next_status))\n",
    )

    helper_start = text.index("    @staticmethod\n    def _metric(")
    helper_end = text.index("    def _update_state_by_elapsed_time(", helper_start)
    text = text[:helper_start] + text[helper_end:]

    forbidden = (
        "self._autonomous_topic:",
        "self._autonomous_topic =",
        "self._autonomous_topic.",
        "self._recent_autonomous_texts",
    )
    if any(pattern in text for pattern in forbidden):
        raise RuntimeError("旧自律話題状態への参照が残っています。")
    AGENT.write_text(text, encoding="utf-8")


def update_facade() -> None:
    FACADE.write_text(
        '''from __future__ import annotations

from app.runtime.agent_life_service import AgentLifeService


class TopicTrackingAgentLifeService(AgentLifeService):
    """互換Import用の別名クラス。

    話題管理は基底``AgentLifeService``自身が``AutonomousTopicTracker``へ委譲する。
    実行時の``__class__``変更は行わない。
    """
''',
        encoding="utf-8",
    )


def update_bootstrap() -> None:
    text = BOOTSTRAP.read_text(encoding="utf-8")
    text = text.replace(
        "from app.runtime.topic_tracking_agent_life_service import (\n"
        "    TopicTrackingAgentLifeService,\n"
        ")\n",
        "",
    )
    text = text.replace(
        "    TopicTrackingAgentLifeService.upgrade_existing(\n"
        "        coordinator._agent_life_service\n"
        "    )\n",
        "",
    )
    BOOTSTRAP.write_text(text, encoding="utf-8")


def update_test() -> None:
    text = TEST.read_text(encoding="utf-8")
    start = text.index("def test_upgrade_existing_preserves_object_identity_and_state()")
    end = text.index("\ndef test_record_autonomous_output_delegates_to_topic_tracker()", start)
    replacement = '''def test_base_service_uses_injected_topic_tracker_without_runtime_class_change() -> None:
    tracker = AutonomousTopicTracker(uuid_factory=lambda: "topic-base")
    service = AgentLifeService(
        ActivityManager(),
        autonomous_topic_tracker=tracker,
    )

    topic = service.record_autonomous_output(
        activity_id="activity-1",
        text="元の話題",
    )

    assert type(service) is AgentLifeService
    assert topic.topic_id == "topic-base"
    assert service.autonomous_topic is tracker.current_topic

'''
    text = text[:start] + replacement + text[end + 1:]
    text = text.replace(
        "def test_interrupt_and_complete_keep_legacy_state_synchronized()",
        "def test_interrupt_and_complete_keep_tracker_state_synchronized()",
    )
    TEST.write_text(text, encoding="utf-8")


def main() -> None:
    update_agent()
    update_facade()
    update_bootstrap()
    update_test()


if __name__ == "__main__":
    main()
