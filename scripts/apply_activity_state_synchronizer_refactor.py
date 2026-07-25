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
    if "self._activity_state_synchronizer.synchronize(" in text:
        print("activity state synchronizer refactor is already applied")
        return

    text = replace_once(
        text,
        "from app.domain.memory import (\n"
        "    EmotionHistoryEntry,\n"
        "    EpisodicMemory,\n"
        "    SemanticMemory,\n"
        "    UnfinishedActivityMemory,\n"
        "    UnrecoveredTopicMemory,\n"
        ")\n",
        "from app.domain.memory import EmotionHistoryEntry, EpisodicMemory, SemanticMemory\n",
    )
    text = replace_once(
        text,
        "from app.runtime.activity_manager import ActivityManager\n",
        "from app.runtime.activity_manager import ActivityManager\n"
        "from app.runtime.activity_state_synchronizer import ActivityStateSynchronizer\n",
    )
    text = replace_once(
        text,
        "        processed_event_registry: ProcessedEventRegistry | None = None,\n"
        "        state_observer: Callable[[AgentState], None] | None = None,\n",
        "        processed_event_registry: ProcessedEventRegistry | None = None,\n"
        "        activity_state_synchronizer: ActivityStateSynchronizer | None = None,\n"
        "        state_observer: Callable[[AgentState], None] | None = None,\n",
    )
    text = replace_once(
        text,
        "        self._processed_event_registry = (\n"
        "            processed_event_registry or ProcessedEventRegistry()\n"
        "        )\n"
        "        self._trace_logger = TraceLogger()\n",
        "        self._processed_event_registry = (\n"
        "            processed_event_registry or ProcessedEventRegistry()\n"
        "        )\n"
        "        self._activity_state_synchronizer = (\n"
        "            activity_state_synchronizer\n"
        "            or ActivityStateSynchronizer(activity_manager)\n"
        "        )\n"
        "        self._trace_logger = TraceLogger()\n",
    )

    start_marker = "    def sync_from_activity_manager(self) -> AgentState:\n"
    end_marker = "    def learn_semantic_fact(\n"
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    replacement = '''    def sync_from_activity_manager(self) -> AgentState:\n        """ActivityManager の状態を AgentState に同期する。"""\n\n        before_memory = self._agent_state.memory\n        self._agent_state = self._activity_state_synchronizer.synchronize(\n            self._agent_state,\n            autonomous_topic=self._autonomous_topic,\n        )\n\n        if self._agent_state.memory != before_memory:\n            self._persist_agent_memory()\n\n        if self._state_observer is not None:\n            try:\n                self._state_observer(self._agent_state)\n            except Exception as error:\n                self._trace_logger.warning(\n                    "agent_life_service:state_observer:failed",\n                    error_type=type(error).__name__,\n                )\n\n        return self._agent_state\n\n'''
    text = text[:start] + replacement + text[end:]

    TARGET.write_text(text, encoding="utf-8")
    print(f"updated {TARGET}")


if __name__ == "__main__":
    main()
