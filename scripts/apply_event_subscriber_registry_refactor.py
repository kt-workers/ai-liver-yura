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
    if "self._event_subscriber_registry.dispatch" in text:
        return

    text = replace_once(
        text,
        "from app.runtime.event_queue import EventQueue\n",
        "from app.runtime.event_queue import EventQueue\n"
        "from app.runtime.event_subscriber_registry import EventSubscriberRegistry\n",
    )
    text = replace_once(
        text,
        "        runtime_diagnostic_snapshot_builder: (\n"
        "            RuntimeDiagnosticSnapshotBuilder | None\n"
        "        ) = None,\n",
        "        runtime_diagnostic_snapshot_builder: (\n"
        "            RuntimeDiagnosticSnapshotBuilder | None\n"
        "        ) = None,\n"
        "        event_subscriber_registry: EventSubscriberRegistry | None = None,\n",
    )
    text = replace_once(
        text,
        "        self._runtime_diagnostic_snapshot_builder = (\n"
        "            runtime_diagnostic_snapshot_builder\n"
        "            or RuntimeDiagnosticSnapshotBuilder()\n"
        "        )\n",
        "        self._runtime_diagnostic_snapshot_builder = (\n"
        "            runtime_diagnostic_snapshot_builder\n"
        "            or RuntimeDiagnosticSnapshotBuilder()\n"
        "        )\n"
        "        self._event_subscriber_registry = (\n"
        "            event_subscriber_registry or EventSubscriberRegistry()\n"
        "        )\n",
    )
    text = replace_once(
        text,
        "        self._event_subscribers: list[\n"
        "            tuple[\n"
        "                AgentEventType,\n"
        "                Callable[[AgentEvent], Awaitable[object]],\n"
        "                Callable[[AgentEvent], bool] | None,\n"
        "            ]\n"
        "        ] = []\n",
        "",
    )
    text = replace_once(
        text,
        "        self._event_subscribers.append((event_type, handler, predicate))\n",
        "        self._event_subscriber_registry.register(\n"
        "            event_type, handler, predicate=predicate\n"
        "        )\n",
    )
    text = replace_once(
        text,
        "            subscriber = next(\n"
        "                (\n"
        "                    handler\n"
        "                    for event_type, handler, predicate in self._event_subscribers\n"
        "                    if filtered_event.event_type == event_type\n"
        "                    and (predicate is None or predicate(filtered_event))\n"
        "                ),\n"
        "                None,\n"
        "            )\n"
        "            if subscriber is not None:\n"
        "                await subscriber(filtered_event)\n"
        "                continue\n",
        "            if await self._event_subscriber_registry.dispatch(filtered_event):\n"
        "                continue\n",
    )

    if "self._event_subscribers" in text:
        raise RuntimeError("旧イベント購読者リストが残っています。")
    TARGET.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
