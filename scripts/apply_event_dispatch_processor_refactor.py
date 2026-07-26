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
    if "self._event_dispatch_processor.process" in text:
        return

    text = replace_once(
        text,
        "from app.runtime.event_buffer import EventBuffer\n",
        "from app.runtime.event_buffer import EventBuffer\n"
        "from app.runtime.event_dispatch_processor import EventDispatchProcessor\n",
    )
    text = replace_once(
        text,
        "        event_ingress_processor: EventIngressProcessor | None = None,\n",
        "        event_ingress_processor: EventIngressProcessor | None = None,\n"
        "        event_dispatch_processor: EventDispatchProcessor | None = None,\n",
    )
    text = replace_once(
        text,
        "        self._conversation_logger = conversation_logger or ConversationLogger()\n",
        "        self._event_dispatch_processor = (\n"
        "            event_dispatch_processor\n"
        "            or EventDispatchProcessor(\n"
        "                event_prioritizer=self._event_prioritizer,\n"
        "                activity_manager=self._activity_manager,\n"
        "                user_input_interruption_coordinator=(\n"
        "                    self._user_input_interruption_coordinator\n"
        "                ),\n"
        "                buffered_event_dispatcher=self._buffered_event_dispatcher,\n"
        "                trace_logger=self._trace_logger,\n"
        "            )\n"
        "        )\n"
        "        self._conversation_logger = conversation_logger or ConversationLogger()\n",
    )

    old = '''            self._trace_logger.write(
                "runtime_coordinator:publish_events:filtered",
                event_type=event.event_type.value,
                event_id=event.event_id,
            )
            prioritized_event = self._event_prioritizer.prioritize(filtered_event)
            foreground_before_input = (
                foreground_at_receipt
                if prioritized_event.event_type == AgentEventType.USER_TEXT
                else self._activity_manager.foreground_activity
            )
            self._user_input_interruption_coordinator.after_prioritization(
                prioritized_event,
                foreground_at_receipt=foreground_before_input,
            )
            self._buffered_event_dispatcher.buffer(prioritized_event)
'''
    new = '''            self._event_dispatch_processor.process(
                original_event=event,
                routed_event=filtered_event,
                foreground_at_receipt=foreground_at_receipt,
            )
'''
    text = replace_once(text, old, new)

    if "self._event_prioritizer.prioritize(filtered_event)" in text:
        raise RuntimeError("publish_eventsに旧配送準備処理が残っています。")
    TARGET.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
