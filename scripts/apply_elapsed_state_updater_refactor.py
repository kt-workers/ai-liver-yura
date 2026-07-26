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
    if "self._elapsed_state_updater.update(" in text:
        return

    text = replace_once(
        text,
        "from app.runtime.emotion_state_updater import EmotionStateUpdater\n",
        "from app.runtime.emotion_state_updater import EmotionStateUpdater\n"
        "from app.runtime.elapsed_state_updater import ElapsedStateUpdater\n",
    )
    text = replace_once(
        text,
        "        conversation_resume_state: ConversationResumeState | None = None,\n"
        "        state_observer: Callable[[AgentState], None] | None = None,\n",
        "        conversation_resume_state: ConversationResumeState | None = None,\n"
        "        elapsed_state_updater: ElapsedStateUpdater | None = None,\n"
        "        state_observer: Callable[[AgentState], None] | None = None,\n",
    )
    text = replace_once(
        text,
        "        self._drive_state_updater = drive_state_updater or DriveStateUpdater()\n"
        "        self._last_drive_updated_at = now or datetime.now(timezone.utc)\n"
        "        self._emotion_appraiser = emotion_appraiser or EmotionAppraiser()\n"
        "        self._emotion_state_updater = emotion_state_updater or EmotionStateUpdater()\n",
        "        self._drive_state_updater = drive_state_updater or DriveStateUpdater()\n"
        "        initial_time = now or datetime.now(timezone.utc)\n"
        "        self._emotion_appraiser = emotion_appraiser or EmotionAppraiser()\n"
        "        self._emotion_state_updater = emotion_state_updater or EmotionStateUpdater()\n"
        "        self._elapsed_state_updater = (\n"
        "            elapsed_state_updater\n"
        "            or ElapsedStateUpdater(\n"
        "                initial_time=initial_time,\n"
        "                drive_state_updater=self._drive_state_updater,\n"
        "                emotion_state_updater=self._emotion_state_updater,\n"
        "            )\n"
        "        )\n",
    )
    text = replace_once(
        text,
        "        self._last_emotion_updated_at = self._last_drive_updated_at\n",
        "",
    )
    text = replace_once(
        text,
        "        self._update_drive_by_elapsed_time(now)\n"
        "        self._update_emotion_by_elapsed_time(now)\n",
        "        self._update_state_by_elapsed_time(now)\n",
    )
    text = replace_once(
        text,
        "        self._last_emotion_updated_at = max(\n"
        "            self._last_emotion_updated_at,\n"
        "            event.occurred_at,\n"
        "        )\n",
        "        self._elapsed_state_updater.record_event(event.occurred_at)\n",
    )
    old_methods = '''    def _update_drive_by_elapsed_time(self, now: datetime) -> None:\n        before_drive = self._agent_state.current_drive\n        elapsed_seconds = (now - self._last_drive_updated_at).total_seconds()\n        updated_drive = self._drive_state_updater.update_by_timestamps(\n            self._agent_state.current_drive,\n            previous_time=self._last_drive_updated_at,\n            current_time=now,\n        )\n        self._agent_state = self._agent_state.with_drive(updated_drive)\n        self._last_drive_updated_at = now\n        after_drive = self._agent_state.current_drive\n        self._trace_logger.write(\n            "agent_life_service:drive_updated_by_elapsed_time",\n            elapsed_seconds=elapsed_seconds,\n            before_curiosity=before_drive.curiosity,\n            before_engagement=before_drive.engagement,\n            before_boredom=before_drive.boredom,\n            before_energy=before_drive.energy,\n            after_curiosity=after_drive.curiosity,\n            after_engagement=after_drive.engagement,\n            after_boredom=after_drive.boredom,\n            after_energy=after_drive.energy,\n        )\n\n    def _update_emotion_by_elapsed_time(self, now: datetime) -> None:\n        before = self._agent_state.current_emotion\n        elapsed_seconds = max(\n            0.0, (now - self._last_emotion_updated_at).total_seconds()\n        )\n        after = self._emotion_state_updater.decay(\n            before, elapsed_seconds=elapsed_seconds\n        )\n        self._agent_state = self._agent_state.with_emotion(after)\n        self._last_emotion_updated_at = max(self._last_emotion_updated_at, now)\n        if after != before:\n            self._trace_logger.debug(\n                "agent_life_service:emotion_decayed",\n                elapsed_seconds=elapsed_seconds,\n                before_mood=before.mood.value,\n                after_mood=after.mood.value,\n                before_arousal=before.arousal,\n                after_arousal=after.arousal,\n                before_valence=before.valence,\n                after_valence=after.valence,\n                before_talkativeness=before.talkativeness,\n                after_talkativeness=after.talkativeness,\n            )\n\n'''
    new_method = '''    def _update_state_by_elapsed_time(self, now: datetime) -> None:\n        result = self._elapsed_state_updater.update(self._agent_state, now=now)\n        self._agent_state = result.state\n        self._trace_logger.write(\n            "agent_life_service:drive_updated_by_elapsed_time",\n            elapsed_seconds=result.drive_elapsed_seconds,\n            before_curiosity=result.before_drive.curiosity,\n            before_engagement=result.before_drive.engagement,\n            before_boredom=result.before_drive.boredom,\n            before_energy=result.before_drive.energy,\n            after_curiosity=result.after_drive.curiosity,\n            after_engagement=result.after_drive.engagement,\n            after_boredom=result.after_drive.boredom,\n            after_energy=result.after_drive.energy,\n        )\n        if result.emotion_changed:\n            self._trace_logger.debug(\n                "agent_life_service:emotion_decayed",\n                elapsed_seconds=result.emotion_elapsed_seconds,\n                before_mood=result.before_emotion.mood.value,\n                after_mood=result.after_emotion.mood.value,\n                before_arousal=result.before_emotion.arousal,\n                after_arousal=result.after_emotion.arousal,\n                before_valence=result.before_emotion.valence,\n                after_valence=result.after_emotion.valence,\n                before_talkativeness=result.before_emotion.talkativeness,\n                after_talkativeness=result.after_emotion.talkativeness,\n            )\n\n'''
    text = replace_once(text, old_methods, new_method)
    TARGET.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
