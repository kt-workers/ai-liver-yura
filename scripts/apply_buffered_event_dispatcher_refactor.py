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
    if "self._buffered_event_dispatcher.buffer" in text:
        return

    text = replace_once(
        text,
        "from app.runtime.behavior_planner import ActivityPlanValidator, BehaviorPlanner\n",
        "from app.runtime.behavior_planner import ActivityPlanValidator, BehaviorPlanner\n"
        "from app.runtime.buffered_event_dispatcher import BufferedEventDispatcher\n",
    )
    text = replace_once(
        text,
        "        user_input_interruption_coordinator: (\n"
        "            UserInputInterruptionCoordinator | None\n"
        "        ) = None,\n",
        "        user_input_interruption_coordinator: (\n"
        "            UserInputInterruptionCoordinator | None\n"
        "        ) = None,\n"
        "        buffered_event_dispatcher: BufferedEventDispatcher | None = None,\n",
    )
    text = replace_once(
        text,
        "        self._event_buffer = event_buffer or EventBuffer()\n",
        "        self._event_buffer = event_buffer or EventBuffer()\n",
    )
    text = replace_once(
        text,
        "        self._trace_logger = TraceLogger()\n",
        "        self._trace_logger = TraceLogger()\n"
        "        self._buffered_event_dispatcher = (\n"
        "            buffered_event_dispatcher\n"
        "            or BufferedEventDispatcher(\n"
        "                event_buffer=self._event_buffer,\n"
        "                event_queue=self._event_queue,\n"
        "                trace_logger=self._trace_logger,\n"
        "            )\n"
        "        )\n",
    )

    old = '''            self._trace_logger.write(
                "runtime_coordinator:publish_events:prioritized",
                event_type=prioritized_event.event_type.value,
                event_id=prioritized_event.event_id,
                priority=prioritized_event.priority,
                discardable=prioritized_event.discardable,
                replace_key=prioritized_event.replace_key,
            )
            self._event_buffer.put(prioritized_event)

        for buffered_event in self._event_buffer.drain():
            self._trace_logger.write(
                "runtime_coordinator:publish_events:queue_put",
                event_type=buffered_event.event_type.value,
                event_id=buffered_event.event_id,
                priority=buffered_event.priority,
                discardable=buffered_event.discardable,
                replace_key=buffered_event.replace_key,
                queue_empty_before_put=self._event_queue.empty(),
            )
            await self._event_queue.put(buffered_event)
'''
    new = '''            self._buffered_event_dispatcher.buffer(prioritized_event)

        await self._buffered_event_dispatcher.flush()
'''
    text = replace_once(text, old, new)

    if "self._event_buffer.put(prioritized_event)" in text:
        raise RuntimeError("publish_eventsに旧バッファ投入処理が残っています。")
    TARGET.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
