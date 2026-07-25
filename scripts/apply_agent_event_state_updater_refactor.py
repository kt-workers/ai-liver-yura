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
    old = (
        "        if event.event_type in (\n"
        "            AgentEventType.USER_TEXT,\n"
        "            AgentEventType.YOUTUBE_COMMENT,\n"
        "            AgentEventType.USER_SPEECH,\n"
        "        ):\n"
        "            self._agent_state = self._agent_state.mark_user_input_received(\n"
        "                event.occurred_at\n"
        "            )\n"
        "            text = event.payload.get(\"text\") or event.payload.get(\"comment\")\n"
    )
    new = (
        "        if event.event_type in (\n"
        "            AgentEventType.USER_TEXT,\n"
        "            AgentEventType.YOUTUBE_COMMENT,\n"
        "            AgentEventType.USER_SPEECH,\n"
        "        ):\n"
        "            text = event.payload.get(\"text\") or event.payload.get(\"comment\")\n"
    )
    if old not in text:
        print("duplicate user input update is already removed")
        return
    text = replace_once(text, old, new)
    TARGET.write_text(text, encoding="utf-8")
    print(f"updated {TARGET}")


if __name__ == "__main__":
    main()
