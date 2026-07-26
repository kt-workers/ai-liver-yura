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
    if "self._event_type_router.route" in text:
        return

    text = replace_once(
        text,
        "from app.runtime.event_subscriber_registry import EventSubscriberRegistry\n",
        "from app.runtime.event_subscriber_registry import EventSubscriberRegistry\n"
        "from app.runtime.event_type_router import EventTypeRouter\n",
    )
    text = replace_once(
        text,
        "        event_dispatch_processor: EventDispatchProcessor | None = None,\n",
        "        event_dispatch_processor: EventDispatchProcessor | None = None,\n"
        "        event_type_router: EventTypeRouter | None = None,\n",
    )
    text = replace_once(
        text,
        "        self._event_dispatch_processor = (\n",
        "        self._event_type_router = (\n"
        "            event_type_router\n"
        "            or EventTypeRouter(\n"
        "                user_input_interruption_coordinator=(\n"
        "                    self._user_input_interruption_coordinator\n"
        "                ),\n"
        "                user_input_event_logger=self._user_input_event_logger,\n"
        "                user_input_event_router=self._user_input_event_router,\n"
        "                behavior_router=self._route_behavior,\n"
        "                behavior_routing_available=lambda: (\n"
        "                    self._behavior_planner is not None\n"
        "                    and self._activity_plan_validator is not None\n"
        "                ),\n"
        "            )\n"
        "        )\n"
        "        self._event_dispatch_processor = (\n",
    )

    old = '''            if filtered_event.event_type == AgentEventType.USER_TEXT:
                self._user_input_interruption_coordinator.before_routing(
                    filtered_event,
                    foreground_at_receipt=foreground_at_receipt,
                )
                self._user_input_event_logger.log(filtered_event)
                routed_event = await self._user_input_event_router.route(
                    filtered_event
                )
                if routed_event is None:
                    continue
                filtered_event = routed_event
            elif (
                filtered_event.event_type == AgentEventType.APP_STARTED
                and self._behavior_planner is not None
                and self._activity_plan_validator is not None
            ):
                routed_event = await self._route_behavior(filtered_event)
                if routed_event is None:
                    continue
                filtered_event = routed_event
'''
    new = '''            routed_event = await self._event_type_router.route(
                filtered_event,
                foreground_at_receipt=foreground_at_receipt,
            )
            if routed_event is None:
                continue
            filtered_event = routed_event
'''
    text = replace_once(text, old, new)

    if "self._user_input_event_router.route" in text[text.index("async def publish_events"):]:
        raise RuntimeError("publish_eventsに旧イベント種別別ルーティングが残っています。")
    TARGET.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
