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
    if "runtime_diagnostic_snapshot_builder: RuntimeDiagnosticSnapshotBuilder | None" in text:
        return

    text = replace_once(
        text,
        "from dataclasses import asdict, replace\n",
        "from dataclasses import replace\n",
    )
    text = replace_once(
        text,
        "from app.runtime.runtime_coordinator import RuntimeCoordinator\n",
        "from app.runtime.runtime_coordinator import RuntimeCoordinator\n",
    ) if False else text
    text = replace_once(
        text,
        "from app.runtime.pending_confirmation import (\n"
        "    ConfirmationResolver,\n"
        "    PendingConfirmationManager,\n"
        ")\n",
        "from app.runtime.pending_confirmation import (\n"
        "    ConfirmationResolver,\n"
        "    PendingConfirmationManager,\n"
        ")\n"
        "from app.runtime.runtime_diagnostic_snapshot_builder import (\n"
        "    RuntimeDiagnosticSnapshotBuilder,\n"
        ")\n",
    )
    text = replace_once(
        text,
        "        autonomous_planning_poll_seconds: float = 0.5,\n"
        "        conversation_logger: ConversationLogger | None = None,\n",
        "        autonomous_planning_poll_seconds: float = 0.5,\n"
        "        conversation_logger: ConversationLogger | None = None,\n"
        "        runtime_diagnostic_snapshot_builder: (\n"
        "            RuntimeDiagnosticSnapshotBuilder | None\n"
        "        ) = None,\n",
    )
    text = replace_once(
        text,
        "        self._plugin_manager = plugin_manager\n"
        "        self._behavior_planner = behavior_planner\n",
        "        self._plugin_manager = plugin_manager\n"
        "        self._runtime_diagnostic_snapshot_builder = (\n"
        "            runtime_diagnostic_snapshot_builder\n"
        "            or RuntimeDiagnosticSnapshotBuilder()\n"
        "        )\n"
        "        self._behavior_planner = behavior_planner\n",
    )

    start = text.index("    def diagnostic_snapshot(self) -> dict[str, object]:")
    end = text.index("    @property\n    def last_behavior_evaluation", start)
    replacement = '''    def diagnostic_snapshot(self) -> dict[str, object]:
        """会話本文や外部秘密を含めず、Coreの現在状態を診断用に返す。"""

        return self._runtime_diagnostic_snapshot_builder.build(
            state=self._agent_life_service.agent_state,
            activity_manager=self._activity_manager,
            plugin_manager=self._plugin_manager,
        )

'''
    text = text[:start] + replacement + text[end:]
    TARGET.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
