from __future__ import annotations

from pathlib import Path


TARGET = Path("app/runtime/agent_life_service.py")


def replace_once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"置換対象の出現数が不正です: expected=1 actual={count}\n{old}"
        )
    return text.replace(old, new, 1)


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    if "self._autonomous_event_planner.plan(" in text:
        return

    text = replace_once(
        text,
        "from app.runtime.autonomous_activity_policy import AutonomousActivityPolicy\n",
        "from app.runtime.autonomous_activity_policy import AutonomousActivityPolicy\n"
        "from app.runtime.autonomous_event_planner import AutonomousEventPlanner\n",
    )
    text = replace_once(
        text,
        "        elapsed_state_updater: ElapsedStateUpdater | None = None,\n"
        "        state_observer: Callable[[AgentState], None] | None = None,\n",
        "        elapsed_state_updater: ElapsedStateUpdater | None = None,\n"
        "        autonomous_event_planner: AutonomousEventPlanner | None = None,\n"
        "        state_observer: Callable[[AgentState], None] | None = None,\n",
    )
    text = replace_once(
        text,
        "        self._autonomous_activity_policy = (\n"
        "            autonomous_activity_policy or AutonomousActivityPolicy()\n"
        "        )\n"
        "        self._agent_memory_store = agent_memory_store\n",
        "        self._autonomous_activity_policy = (\n"
        "            autonomous_activity_policy or AutonomousActivityPolicy()\n"
        "        )\n"
        "        self._autonomous_event_planner = (\n"
        "            autonomous_event_planner\n"
        "            or AutonomousEventPlanner(\n"
        "                activity_manager,\n"
        "                autonomous_activity_policy=self._autonomous_activity_policy,\n"
        "                autonomous_plan_state=self._autonomous_plan_state,\n"
        "                conversation_resume_state=self._conversation_resume_state,\n"
        "                pending_confirmation_provider=(\n"
        "                    self._pending_confirmation_provider\n"
        "                ),\n"
        "                conversation_idle_timeout_seconds=(\n"
        "                    self._conversation_idle_timeout_seconds\n"
        "                ),\n"
        "            )\n"
        "        )\n"
        "        self._agent_memory_store = agent_memory_store\n",
    )

    method_start = text.index("    def plan_next_event(")
    method_end = text.index("    def end_conversation(", method_start)
    new_method = '''    def plan_next_event(self, now: datetime | None = None) -> AgentEvent | None:
        """現在状態から、次に発生させる自律 Event を判断する。"""

        now = now or datetime.now(timezone.utc)
        self._update_state_by_elapsed_time(now)
        self.sync_from_activity_manager()
        self._trace_logger.write(
            "agent_life_service:plan_next_event:start",
            active_activity_exists=self._agent_state.active_activity is not None,
            pending_activity_count=len(self._agent_state.pending_activities),
            suspended_activity_count=len(self._agent_state.suspended_activities),
            drive_curiosity=self._agent_state.current_drive.curiosity,
            drive_engagement=self._agent_state.current_drive.engagement,
            drive_boredom=self._agent_state.current_drive.boredom,
            drive_energy=self._agent_state.current_drive.energy,
            emotion_mood=self._agent_state.current_emotion.mood.value,
            emotion_talkativeness=self._agent_state.current_emotion.talkativeness,
        )

        result = self._autonomous_event_planner.plan(
            self._agent_state,
            now=now,
            awakening_completed_at=self._awakening_completed_at,
            continuation_provider=lambda: self._evaluate_topic_continuation(now),
            autonomous_topic_provider=lambda: self._autonomous_topic,
        )
        log_method = (
            self._trace_logger.debug
            if result.log_level == "debug"
            else self._trace_logger.write
        )
        log_method(result.log_event, **result.details)
        return result.event

'''
    text = text[:method_start] + new_method + text[method_end:]

    resume_start = text.index("    def _conversation_resume_reason(")
    resume_end = text.index("    def handle_event(", resume_start)
    text = text[:resume_start] + text[resume_end:]

    interval_start = text.index("    def _autonomous_talk_interval_seconds(")
    text = text[:interval_start].rstrip() + "\n"

    TARGET.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
