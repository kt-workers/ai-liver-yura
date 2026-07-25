from __future__ import annotations

from pathlib import Path


TARGET = Path("app/runtime/agent_life_service.py")


def replace_once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"置換対象の出現数が不正です: expected=1 actual={count}\n{old}")
    return text.replace(old, new, 1)


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    if "from app.runtime.processed_event_registry import ProcessedEventRegistry" in text:
        print("processed event registry refactor is already applied")
        return

    text = replace_once(text, "from collections import deque\n", "")
    text = replace_once(
        text,
        "from app.runtime.relationship_state_updater import RelationshipStateUpdater\n",
        "from app.runtime.processed_event_registry import ProcessedEventRegistry\n"
        "from app.runtime.relationship_state_updater import RelationshipStateUpdater\n",
    )
    text = replace_once(
        text,
        "        autonomous_plan_retry_backoff_seconds: float = 2.0,\n"
        "        state_observer: Callable[[AgentState], None] | None = None,\n",
        "        autonomous_plan_retry_backoff_seconds: float = 2.0,\n"
        "        processed_event_registry: ProcessedEventRegistry | None = None,\n"
        "        state_observer: Callable[[AgentState], None] | None = None,\n",
    )
    text = replace_once(
        text,
        "        self._agent_memory_store = agent_memory_store\n"
        "        self._processed_event_ids: deque[str] = deque(maxlen=1024)\n"
        "        self._processed_event_id_set: set[str] = set()\n",
        "        self._agent_memory_store = agent_memory_store\n"
        "        self._processed_event_registry = (\n"
        "            processed_event_registry or ProcessedEventRegistry()\n"
        "        )\n",
    )
    text = replace_once(
        text,
        "        if event.event_id in self._processed_event_id_set:\n"
        "            self._trace_logger.debug(\n"
        "                \"agent_life_service:handle_event:duplicate_skipped\",\n"
        "                event_id=event.event_id,\n"
        "                event_type=event.event_type.value,\n"
        "            )\n"
        "            return self.sync_from_activity_manager()\n"
        "        if len(self._processed_event_ids) == self._processed_event_ids.maxlen:\n"
        "            oldest = self._processed_event_ids[0]\n"
        "            self._processed_event_id_set.discard(oldest)\n"
        "        self._processed_event_ids.append(event.event_id)\n"
        "        self._processed_event_id_set.add(event.event_id)\n",
        "        if not self._processed_event_registry.register(event.event_id):\n"
        "            self._trace_logger.debug(\n"
        "                \"agent_life_service:handle_event:duplicate_skipped\",\n"
        "                event_id=event.event_id,\n"
        "                event_type=event.event_type.value,\n"
        "            )\n"
        "            return self.sync_from_activity_manager()\n",
    )

    TARGET.write_text(text, encoding="utf-8")
    print(f"updated {TARGET}")


if __name__ == "__main__":
    main()
