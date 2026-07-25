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
    if "self._agent_event_state_updater.update(" in text:
        print("agent event state updater refactor is already applied")
        return

    text = replace_once(
        text,
        "from dataclasses import asdict\n",
        "",
    )
    text = replace_once(
        text,
        "from app.domain.memory import EmotionHistoryEntry, EpisodicMemory, SemanticMemory\n",
        "from app.domain.memory import SemanticMemory\n",
    )
    text = replace_once(
        text,
        "from app.runtime.activity_state_synchronizer import ActivityStateSynchronizer\n",
        "from app.runtime.activity_state_synchronizer import ActivityStateSynchronizer\n"
        "from app.runtime.agent_event_state_updater import AgentEventStateUpdater\n",
    )
    text = replace_once(
        text,
        "        activity_state_synchronizer: ActivityStateSynchronizer | None = None,\n"
        "        state_observer: Callable[[AgentState], None] | None = None,\n",
        "        activity_state_synchronizer: ActivityStateSynchronizer | None = None,\n"
        "        agent_event_state_updater: AgentEventStateUpdater | None = None,\n"
        "        state_observer: Callable[[AgentState], None] | None = None,\n",
    )
    text = replace_once(
        text,
        "        self._activity_state_synchronizer = (\n"
        "            activity_state_synchronizer\n"
        "            or ActivityStateSynchronizer(activity_manager)\n"
        "        )\n"
        "        self._trace_logger = TraceLogger()\n",
        "        self._activity_state_synchronizer = (\n"
        "            activity_state_synchronizer\n"
        "            or ActivityStateSynchronizer(activity_manager)\n"
        "        )\n"
        "        self._agent_event_state_updater = (\n"
        "            agent_event_state_updater\n"
        "            or AgentEventStateUpdater(\n"
        "                drive_state_updater=self._drive_state_updater,\n"
        "                emotion_appraiser=self._emotion_appraiser,\n"
        "                emotion_state_updater=self._emotion_state_updater,\n"
        "                relationship_state_updater=self._relationship_state_updater,\n"
        "            )\n"
        "        )\n"
        "        self._trace_logger = TraceLogger()\n",
    )

    start_marker = "        before_drive = self._agent_state.current_drive\n"
    end_marker = "        if event.event_type in (\n            AgentEventType.USER_TEXT,\n"
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    replacement = '''        update_result = self._agent_event_state_updater.update(
            self._agent_state,
            event,
        )
        self._agent_state = update_result.state
        self._last_emotion_updated_at = max(
            self._last_emotion_updated_at,
            event.occurred_at,
        )

        self._trace_logger.write(
            "agent_life_service:handle_event:drive_updated",
            event_type=event.event_type.value,
            before_curiosity=update_result.before_drive.curiosity,
            before_engagement=update_result.before_drive.engagement,
            before_boredom=update_result.before_drive.boredom,
            before_energy=update_result.before_drive.energy,
            after_curiosity=update_result.after_drive.curiosity,
            after_engagement=update_result.after_drive.engagement,
            after_boredom=update_result.after_drive.boredom,
            after_energy=update_result.after_drive.energy,
        )
        self._trace_logger.info(
            "agent_life_service:handle_event:emotion_updated",
            event_type=event.event_type.value,
            source_event_id=event.event_id,
            appraisal_reason=update_result.appraisal.reason,
            before_arousal=update_result.before_emotion.arousal,
            before_valence=update_result.before_emotion.valence,
            before_talkativeness=update_result.before_emotion.talkativeness,
            after_arousal=update_result.after_emotion.arousal,
            after_valence=update_result.after_emotion.valence,
            after_talkativeness=update_result.after_emotion.talkativeness,
        )

        after_relationship = update_result.after_relationship
        if update_result.relationship_changed and after_relationship is not None:
            self._trace_logger.info(
                "agent_life_service:relationship_updated",
                source_event_id=event.event_id,
                counterpart_id=after_relationship.counterpart_id,
                role=after_relationship.role,
                familiarity=after_relationship.familiarity,
                interaction_count=after_relationship.interaction_count,
            )
            self._persist_relationship_memory(
                update_result.relationship_memory,
                event.event_id,
            )

        self._persist_agent_memory()

'''
    text = text[:start] + replacement + text[end:]

    text = replace_once(
        text,
        "\n        if event.event_type == AgentEventType.SPEECH_STARTED:\n"
        "            self._agent_state = self._agent_state.mark_speech_started(event.occurred_at)\n"
        "\n"
        "        if event.event_type == AgentEventType.SPEECH_FINISHED:\n"
        "            self._agent_state = self._agent_state.mark_speech_finished(event.occurred_at)\n",
        "",
    )

    TARGET.write_text(text, encoding="utf-8")
    print(f"updated {TARGET}")


if __name__ == "__main__":
    main()
