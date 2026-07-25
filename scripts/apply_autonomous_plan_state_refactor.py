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
    if "self._autonomous_plan_state.accept(event)" in text:
        print("autonomous plan state refactor is already applied")
        return

    text = replace_once(
        text,
        "from app.runtime.autonomous_activity_policy import AutonomousActivityPolicy\n",
        "from app.runtime.autonomous_activity_policy import AutonomousActivityPolicy\n"
        "from app.runtime.autonomous_plan_state import AutonomousPlanState\n",
    )
    text = replace_once(
        text,
        "        agent_event_state_updater: AgentEventStateUpdater | None = None,\n"
        "        state_observer: Callable[[AgentState], None] | None = None,\n",
        "        agent_event_state_updater: AgentEventStateUpdater | None = None,\n"
        "        autonomous_plan_state: AutonomousPlanState | None = None,\n"
        "        state_observer: Callable[[AgentState], None] | None = None,\n",
    )
    text = replace_once(
        text,
        "        self._last_emotion_updated_at = self._last_drive_updated_at\n"
        "        self._last_autonomous_talk_planned_at: datetime | None = None\n"
        "        self._last_autonomous_plan_rejected_at: datetime | None = None\n"
        "        self._awakening_completed_at: datetime | None = None\n"
        "        self._autonomous_plan_retry_backoff_seconds = max(\n"
        "            autonomous_plan_retry_backoff_seconds, 0.0\n"
        "        )\n"
        "        self._autonomous_reconsider_after_seconds = (\n"
        "            self._autonomous_plan_retry_backoff_seconds\n"
        "        )\n",
        "        self._last_emotion_updated_at = self._last_drive_updated_at\n"
        "        self._awakening_completed_at: datetime | None = None\n"
        "        self._autonomous_plan_state = (\n"
        "            autonomous_plan_state\n"
        "            or AutonomousPlanState(\n"
        "                default_retry_backoff_seconds=autonomous_plan_retry_backoff_seconds\n"
        "            )\n"
        "        )\n",
    )
    text = replace_once(
        text,
        "        if self._is_within_pause(\n"
        "            since=self._last_autonomous_plan_rejected_at,\n"
        "            now=now,\n"
        "            pause_seconds=self._autonomous_reconsider_after_seconds,\n"
        "        ):\n",
        "        if self._autonomous_plan_state.is_retry_backoff_active(now):\n",
    )
    text = text.replace(
        "self._autonomous_reconsider_after_seconds",
        "self._autonomous_plan_state.reconsider_after_seconds",
    )
    text = text.replace(
        "self._last_autonomous_plan_rejected_at",
        "self._autonomous_plan_state.last_rejected_at",
    )
    text = replace_once(
        text,
        "        if not is_autonomous_lookahead and self._is_within_pause(\n"
        "            since=self._last_autonomous_talk_planned_at,\n"
        "            now=now,\n"
        "            pause_seconds=autonomous_talk_interval_seconds,\n"
        "        ):\n",
        "        if (\n"
        "            not is_autonomous_lookahead\n"
        "            and self._autonomous_plan_state.is_talk_interval_active(\n"
        "                now, autonomous_talk_interval_seconds\n"
        "            )\n"
        "        ):\n",
    )
    text = text.replace(
        "self._last_autonomous_talk_planned_at",
        "self._autonomous_plan_state.last_accepted_at",
    )

    old_accept = '''        if event.event_type == AgentEventType.CURIOSITY_PEAK:\n            planned_for = event.payload.get("autonomous_planned_for")\n            try:\n                accepted_at = (\n                    datetime.fromisoformat(planned_for)\n                    if isinstance(planned_for, str)\n                    else event.occurred_at\n                )\n            except ValueError:\n                accepted_at = event.occurred_at\n            self._autonomous_plan_state.last_accepted_at = accepted_at\n            self._autonomous_plan_state.last_rejected_at = None\n            self._autonomous_plan_state.reconsider_after_seconds = (\n                self._autonomous_plan_retry_backoff_seconds\n            )\n            self._explicit_resume_reason = None\n            self._observed_ongoing_activity_id = None\n            self._trace_logger.write(\n                "agent_life_service:autonomous_plan:accepted",\n                source_event_id=event.event_id,\n                planned_for=accepted_at,\n            )\n'''
    new_accept = '''        accepted_at = self._autonomous_plan_state.accept(event)\n        if accepted_at is not None:\n            self._explicit_resume_reason = None\n            self._observed_ongoing_activity_id = None\n            self._trace_logger.write(\n                "agent_life_service:autonomous_plan:accepted",\n                source_event_id=event.event_id,\n                planned_for=accepted_at,\n            )\n'''
    text = replace_once(text, old_accept, new_accept)

    old_reject = '''        if event.event_type != AgentEventType.CURIOSITY_PEAK:\n            return\n        self._autonomous_plan_state.last_rejected_at = (\n            rejected_at or datetime.now(timezone.utc)\n        )\n        self._autonomous_plan_state.reconsider_after_seconds = (\n            min(300.0, max(5.0, reconsider_after_seconds))\n            if reconsider_after_seconds is not None\n            else self._autonomous_plan_retry_backoff_seconds\n        )\n        self._trace_logger.write(\n            "agent_life_service:autonomous_plan:rejected",\n            source_event_id=event.event_id,\n            rejected_at=self._autonomous_plan_state.last_rejected_at,\n            retry_backoff_seconds=self._autonomous_plan_state.reconsider_after_seconds,\n        )\n'''
    new_reject = '''        if not self._autonomous_plan_state.reject(\n            event,\n            rejected_at=rejected_at,\n            reconsider_after_seconds=reconsider_after_seconds,\n        ):\n            return\n        self._trace_logger.write(\n            "agent_life_service:autonomous_plan:rejected",\n            source_event_id=event.event_id,\n            rejected_at=self._autonomous_plan_state.last_rejected_at,\n            retry_backoff_seconds=self._autonomous_plan_state.reconsider_after_seconds,\n        )\n'''
    text = replace_once(text, old_reject, new_reject)

    TARGET.write_text(text, encoding="utf-8")
    print(f"updated {TARGET}")


if __name__ == "__main__":
    main()
