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
    if "self._user_input_event_logger.log" in text:
        return

    text = replace_once(
        text,
        "from app.runtime.user_input_interruption_coordinator import (\n"
        "    UserInputInterruptionCoordinator,\n"
        ")\n",
        "from app.runtime.user_input_event_logger import UserInputEventLogger\n"
        "from app.runtime.user_input_interruption_coordinator import (\n"
        "    UserInputInterruptionCoordinator,\n"
        ")\n",
    )
    text = replace_once(
        text,
        "        buffered_event_dispatcher: BufferedEventDispatcher | None = None,\n",
        "        buffered_event_dispatcher: BufferedEventDispatcher | None = None,\n"
        "        user_input_event_logger: UserInputEventLogger | None = None,\n",
    )
    text = replace_once(
        text,
        "        self._trace_logger = TraceLogger()\n",
        "        self._trace_logger = TraceLogger()\n"
        "        self._user_input_event_logger = (\n"
        "            user_input_event_logger\n"
        "            or UserInputEventLogger(self._trace_logger)\n"
        "        )\n",
    )

    old = '''                self._trace_logger.info(
                    "runtime_coordinator:event_received",
                    **filtered_event.trace_context.as_log_fields(),
                    event_type=filtered_event.event_type.value,
                    source=str(filtered_event.payload.get("source") or "unknown"),
                    priority=filtered_event.priority,
                )
                self._trace_logger.user_input(
                    source=str(filtered_event.payload.get("source") or "unknown"),
                    event_id=filtered_event.event_id,
                    text=str(filtered_event.payload.get("text") or ""),
                    trace_id=filtered_event.trace_context.trace_id,
                    parent_trace_id=filtered_event.trace_context.parent_trace_id,
                    activity_turn_id=filtered_event.trace_context.activity_turn_id,
                    confirmation_id=filtered_event.trace_context.confirmation_id,
                )
'''
    text = replace_once(
        text,
        old,
        "                self._user_input_event_logger.log(filtered_event)\n",
    )

    if "runtime_coordinator:event_received" in text:
        raise RuntimeError("RuntimeCoordinatorに旧ユーザー入力ログ処理が残っています。")
    TARGET.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
