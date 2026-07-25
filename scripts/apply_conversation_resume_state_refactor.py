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
    if "self._conversation_resume_state.resolve_reason(" in text:
        print("conversation resume state refactor is already applied")
        return

    text = replace_once(
        text,
        "from app.runtime.autonomous_plan_state import AutonomousPlanState\n",
        "from app.runtime.autonomous_plan_state import AutonomousPlanState\n"
        "from app.runtime.conversation_resume_state import ConversationResumeState\n",
    )
    text = replace_once(
        text,
        "        autonomous_plan_state: AutonomousPlanState | None = None,\n"
        "        state_observer: Callable[[AgentState], None] | None = None,\n",
        "        autonomous_plan_state: AutonomousPlanState | None = None,\n"
        "        conversation_resume_state: ConversationResumeState | None = None,\n"
        "        state_observer: Callable[[AgentState], None] | None = None,\n",
    )
    text = replace_once(
        text,
        "        self._conversation_idle_timeout_seconds = conversation_idle_timeout_seconds\n"
        "        self._observed_ongoing_activity_id: str | None = None\n"
        "        self._explicit_resume_reason: str | None = None\n",
        "        self._conversation_idle_timeout_seconds = conversation_idle_timeout_seconds\n"
        "        self._conversation_resume_state = (\n"
        "            conversation_resume_state or ConversationResumeState()\n"
        "        )\n",
    )
    text = replace_once(
        text,
        "            self._observed_ongoing_activity_id = ongoing_activity.ongoing_activity_id\n",
        "            self._conversation_resume_state.observe_ongoing_activity(\n"
        "                ongoing_activity.ongoing_activity_id\n"
        "            )\n",
    )
    text = replace_once(
        text,
        "        self._explicit_resume_reason = reason\n",
        "        self._conversation_resume_state.end_conversation(reason)\n",
    )
    text = replace_once(
        text,
        "    def _conversation_resume_reason(self, now: datetime) -> str | None:\n"
        "        if self._explicit_resume_reason is not None:\n"
        "            return f\"conversation_ended:{self._explicit_resume_reason}\"\n"
        "        if self._observed_ongoing_activity_id is not None:\n"
        "            return f\"ongoing_activity_completed:{self._observed_ongoing_activity_id}\"\n"
        "        if (\n"
        "            self._agent_state.last_user_input_at is not None\n"
        "            and not self._is_within_pause(\n"
        "                since=self._agent_state.last_user_input_at,\n"
        "                now=now,\n"
        "                pause_seconds=self._conversation_idle_timeout_seconds,\n"
        "            )\n"
        "        ):\n"
        "            return \"conversation_idle_timeout\"\n"
        "        if self._agent_state.last_user_input_at is None:\n"
        "            return \"no_conversation\"\n"
        "        return None\n",
        "    def _conversation_resume_reason(self, now: datetime) -> str | None:\n"
        "        return self._conversation_resume_state.resolve_reason(\n"
        "            last_user_input_at=self._agent_state.last_user_input_at,\n"
        "            now=now,\n"
        "            idle_timeout_seconds=self._conversation_idle_timeout_seconds,\n"
        "        )\n",
    )
    text = replace_once(
        text,
        "        if accepted_at is not None:\n"
        "            self._explicit_resume_reason = None\n"
        "            self._observed_ongoing_activity_id = None\n",
        "        if accepted_at is not None:\n"
        "            self._conversation_resume_state.clear_after_plan_accepted()\n",
    )

    TARGET.write_text(text, encoding="utf-8")
    print(f"updated {TARGET}")


if __name__ == "__main__":
    main()
