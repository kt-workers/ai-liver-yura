from __future__ import annotations

from pathlib import Path


TARGET = Path("app/runtime/runtime_coordinator.py")


def replace_once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"置換対象の出現数が不正です: expected=1 actual={count}\n{old}"
        )
    return text.replace(old, new, 1)


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    if "self._conversation_input_recorder.record" in text:
        return

    text = replace_once(
        text,
        "from app.runtime.behavior_planner import ActivityPlanValidator, BehaviorPlanner\n",
        "from app.runtime.behavior_planner import ActivityPlanValidator, BehaviorPlanner\n"
        "from app.runtime.conversation_input_recorder import ConversationInputRecorder\n",
    )
    text = replace_once(
        text,
        "        conversation_logger: ConversationLogger | None = None,\n",
        "        conversation_logger: ConversationLogger | None = None,\n"
        "        conversation_input_recorder: ConversationInputRecorder | None = None,\n",
    )
    text = replace_once(
        text,
        "        self._conversation_logger = conversation_logger or ConversationLogger()\n",
        "        self._conversation_logger = conversation_logger or ConversationLogger()\n"
        "        self._conversation_input_recorder = (\n"
        "            conversation_input_recorder\n"
        "            or ConversationInputRecorder(self._conversation_logger)\n"
        "        )\n",
    )
    text = replace_once(
        text,
        "            self._record_conversation_input(filtered_event)\n",
        "            self._conversation_input_recorder.record(filtered_event)\n",
    )

    start = text.index("    def _record_conversation_input(")
    end = text.index("    def _has_plugin_capability(", start)
    text = text[:start] + text[end:]

    if "def _record_conversation_input(" in text:
        raise RuntimeError("旧会話入力記録メソッドが残っています。")
    TARGET.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
