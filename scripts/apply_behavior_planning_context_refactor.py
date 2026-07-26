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


def remove_between(text: str, start: str, end: str) -> str:
    start_index = text.index(start)
    end_index = text.index(end, start_index)
    return text[:start_index] + text[end_index:]


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    if "self._behavior_planning_context_builder.build" in text:
        return

    text = replace_once(
        text,
        "from app.runtime.behavior_planner import ActivityPlanValidator, BehaviorPlanner\n",
        "from app.runtime.behavior_planner import ActivityPlanValidator, BehaviorPlanner\n"
        "from app.runtime.behavior_planning_context_builder import (\n"
        "    BehaviorPlanningContextBuilder,\n"
        ")\n",
    )
    text = replace_once(
        text,
        "        event_type_router: EventTypeRouter | None = None,\n",
        "        event_type_router: EventTypeRouter | None = None,\n"
        "        behavior_planning_context_builder: (\n"
        "            BehaviorPlanningContextBuilder | None\n"
        "        ) = None,\n",
    )
    text = replace_once(
        text,
        "        self._event_dispatch_processor = (\n",
        "        self._behavior_planning_context_builder = (\n"
        "            behavior_planning_context_builder\n"
        "            or (\n"
        "                BehaviorPlanningContextBuilder(\n"
        "                    activity_manager=self._activity_manager,\n"
        "                    agent_life_service=self._agent_life_service,\n"
        "                    plugin_manager=self._plugin_manager,\n"
        "                    activity_registry=self._activity_registry,\n"
        "                    short_term_memory=short_term_memory,\n"
        "                    topic_history=topic_history,\n"
        "                )\n"
        "                if self._plugin_manager is not None\n"
        "                else None\n"
        "            )\n"
        "        )\n"
        "        self._event_dispatch_processor = (\n",
    )

    start = "        agent_state = self._agent_life_service.agent_state\n"
    end = "        situation_payload: dict[str, object]\n"
    start_index = text.index(start, text.index("    async def _route_behavior"))
    end_index = text.index(end, start_index)
    replacement = (
        "        context_builder = self._behavior_planning_context_builder\n"
        "        if context_builder is None:\n"
        "            return self._with_plugin_availability(event)\n"
        "        preparation = context_builder.build(event)\n"
        "        event = preparation.event\n"
        "        planning_context = preparation.context\n"
        "        ongoing = preparation.ongoing_activity\n"
    )
    text = text[:start_index] + replacement + text[end_index:]

    text = remove_between(
        text,
        "    def _conversation_history(self) -> tuple[dict[str, object], ...]:\n",
        "    async def _route_behavior(self, event: AgentEvent) -> AgentEvent | None:\n",
    )
    text = remove_between(
        text,
        "    @staticmethod\n    def _ongoing_planning_context(\n",
        "    @staticmethod\n    def _ongoing_transition_payload(\n",
    )

    if "self._conversation_history()" in text:
        raise RuntimeError("RuntimeCoordinatorに会話履歴組み立てが残っています。")
    if "self._ongoing_planning_context(ongoing)" in text:
        raise RuntimeError("RuntimeCoordinatorにOngoing Context組み立てが残っています。")
    TARGET.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
