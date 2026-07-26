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
    if "self._user_input_event_router.route" in text:
        return

    text = replace_once(
        text,
        "from app.runtime.user_input_event_logger import UserInputEventLogger\n",
        "from app.runtime.user_input_event_logger import UserInputEventLogger\n"
        "from app.runtime.user_input_event_router import UserInputEventRouter\n",
    )
    text = replace_once(
        text,
        "        user_input_event_logger: UserInputEventLogger | None = None,\n",
        "        user_input_event_logger: UserInputEventLogger | None = None,\n"
        "        user_input_event_router: UserInputEventRouter | None = None,\n",
    )
    text = replace_once(
        text,
        "        self._user_input_event_logger = (\n"
        "            user_input_event_logger\n"
        "            or UserInputEventLogger(self._trace_logger)\n"
        "        )\n",
        "        self._user_input_event_logger = (\n"
        "            user_input_event_logger\n"
        "            or UserInputEventLogger(self._trace_logger)\n"
        "        )\n"
        "        self._user_input_event_router = (\n"
        "            user_input_event_router\n"
        "            or UserInputEventRouter(\n"
        "                behavior_router=self._route_behavior,\n"
        "                plugin_router=self._route_plugin_user_input,\n"
        "                fallback=self._with_plugin_availability,\n"
        "                behavior_routing_available=lambda: (\n"
        "                    self._behavior_planner is not None\n"
        "                    and self._activity_plan_validator is not None\n"
        "                ),\n"
        "                plugin_routing_available=lambda: self._has_plugin_capability(\n"
        "                    PluginCapability.USER_INTENT_INTERPRETER.value\n"
        "                ),\n"
        "            )\n"
        "        )\n",
    )

    old = '''                if (
                    self._behavior_planner is not None
                    and self._activity_plan_validator is not None
                ):
                    routed_event = await self._route_behavior(filtered_event)
                elif self._has_plugin_capability(
                    PluginCapability.USER_INTENT_INTERPRETER.value
                ):
                    routed_event = await self._route_plugin_user_input(filtered_event)
                else:
                    routed_event = self._with_plugin_availability(filtered_event)
'''
    text = replace_once(
        text,
        old,
        "                routed_event = await self._user_input_event_router.route(\n"
        "                    filtered_event\n"
        "                )\n",
    )

    if "elif self._has_plugin_capability(" in text:
        raise RuntimeError("旧ユーザー入力ルーティング分岐が残っています。")
    TARGET.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
