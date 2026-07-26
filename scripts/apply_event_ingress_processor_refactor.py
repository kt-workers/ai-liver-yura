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
    if "self._event_ingress_processor.process" in text:
        return

    text = replace_once(
        text,
        "from app.runtime.event_filter import DefaultEventFilter, EventFilter\n",
        "from app.runtime.event_filter import DefaultEventFilter, EventFilter\n"
        "from app.runtime.event_ingress_processor import EventIngressProcessor\n",
    )
    text = replace_once(
        text,
        "        event_subscriber_registry: EventSubscriberRegistry | None = None,\n",
        "        event_subscriber_registry: EventSubscriberRegistry | None = None,\n"
        "        event_ingress_processor: EventIngressProcessor | None = None,\n",
    )
    text = replace_once(
        text,
        "        self._conversation_input_recorder = (\n"
        "            conversation_input_recorder\n"
        "            or ConversationInputRecorder(self._conversation_logger)\n"
        "        )\n",
        "        self._conversation_input_recorder = (\n"
        "            conversation_input_recorder\n"
        "            or ConversationInputRecorder(self._conversation_logger)\n"
        "        )\n"
        "        self._event_ingress_processor = (\n"
        "            event_ingress_processor\n"
        "            or EventIngressProcessor(\n"
        "                event_filter=self._event_filter,\n"
        "                activity_manager=self._activity_manager,\n"
        "                conversation_input_recorder=self._conversation_input_recorder,\n"
        "                agent_life_service=self._agent_life_service,\n"
        "                event_subscriber_registry=self._event_subscriber_registry,\n"
        "            )\n"
        "        )\n",
    )

    old = '''        for event in events:
            filtered_event = self._event_filter.filter(event)
            if filtered_event is None:
                continue
            foreground_at_receipt = self._activity_manager.foreground_activity
            self._conversation_input_recorder.record(filtered_event)
            self._agent_life_service.handle_event(filtered_event)
            if await self._event_subscriber_registry.dispatch(filtered_event):
                continue
'''
    new = '''        for event in events:
            ingress_result = await self._event_ingress_processor.process(event)
            filtered_event = ingress_result.event
            if filtered_event is None or ingress_result.consumed:
                continue
            foreground_at_receipt = ingress_result.foreground_at_receipt
'''
    text = replace_once(text, old, new)

    if "self._event_filter.filter(event)" in text:
        raise RuntimeError("publish_eventsに旧イベント入口処理が残っています。")
    TARGET.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
