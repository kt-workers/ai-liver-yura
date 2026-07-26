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
    if "self._user_input_interruption_coordinator.before_routing" in text:
        return

    text = replace_once(
        text,
        "from app.runtime.runtime_diagnostic_snapshot_builder import (\n"
        "    RuntimeDiagnosticSnapshotBuilder,\n"
        ")\n",
        "from app.runtime.runtime_diagnostic_snapshot_builder import (\n"
        "    RuntimeDiagnosticSnapshotBuilder,\n"
        ")\n"
        "from app.runtime.user_input_interruption_coordinator import (\n"
        "    UserInputInterruptionCoordinator,\n"
        ")\n",
    )
    text = replace_once(
        text,
        "        event_subscriber_registry: EventSubscriberRegistry | None = None,\n",
        "        event_subscriber_registry: EventSubscriberRegistry | None = None,\n"
        "        user_input_interruption_coordinator: (\n"
        "            UserInputInterruptionCoordinator | None\n"
        "        ) = None,\n",
    )
    text = replace_once(
        text,
        "        self._trace_logger = TraceLogger()\n"
        "        self._conversation_logger = conversation_logger or ConversationLogger()\n",
        "        self._trace_logger = TraceLogger()\n"
        "        self._user_input_interruption_coordinator = (\n"
        "            user_input_interruption_coordinator\n"
        "            or UserInputInterruptionCoordinator(\n"
        "                activity_manager=self._activity_manager,\n"
        "                action_scheduler=self._action_scheduler,\n"
        "                activity_planner_thread=self._activity_planner_thread,\n"
        "                activity_executor_thread=self._activity_executor_thread,\n"
        "                agent_life_service=self._agent_life_service,\n"
        "                trace_logger=self._trace_logger,\n"
        "            )\n"
        "        )\n"
        "        self._conversation_logger = conversation_logger or ConversationLogger()\n",
    )
    text = replace_once(
        text,
        "            if filtered_event.event_type == AgentEventType.USER_TEXT:\n"
        "                if (\n"
        "                    foreground_at_receipt is not None\n"
        "                    and foreground_at_receipt.activity_type\n"
        "                    == ActivityType.AUTONOMOUS_TALK\n"
        "                ):\n"
        "                    self._action_scheduler.cancel_pending_segments(\n"
        "                        foreground_at_receipt.activity_id\n"
        "                    )\n"
        "                self._trace_logger.info(\n",
        "            if filtered_event.event_type == AgentEventType.USER_TEXT:\n"
        "                self._user_input_interruption_coordinator.before_routing(\n"
        "                    filtered_event,\n"
        "                    foreground_at_receipt=foreground_at_receipt,\n"
        "                )\n"
        "                self._trace_logger.info(\n",
    )
    old = """            foreground_before_input = (
                foreground_at_receipt
                if prioritized_event.event_type == AgentEventType.USER_TEXT
                else self._activity_manager.foreground_activity
            )
            prepared_activity = self._activity_manager.prepare_user_input(
                prioritized_event
            )
            if prioritized_event.event_type == AgentEventType.USER_TEXT:
                self._activity_planner_thread.cancel_inflight_autonomous(
                    source_event_id=prioritized_event.event_id,
                    trace_context=prioritized_event.trace_context,
                )
                if (
                    foreground_before_input is not None
                    and foreground_before_input.activity_type
                    == ActivityType.AUTONOMOUS_TALK
                ):
                    self._agent_life_service.interrupt_autonomous_topic(
                        activity_id=foreground_before_input.activity_id,
                        fallback_text=foreground_before_input.goal,
                    )
                discarded_deferred = self._activity_manager.discard_deferred_autonomous(
                    reason="user_conversation_started"
                )
                canceled = self._activity_executor_thread.cancel_pending_autonomous(
                    source_event_id=prioritized_event.event_id,
                    reason="user_text_received",
                )
                if canceled:
                    self._trace_logger.info(
                        "runtime_coordinator:user_input:pending_autonomous_canceled",
                        event_id=prioritized_event.event_id,
                        planned_activity_ids=[
                            item.planned_activity_id for item in canceled
                        ],
                        activity_ids=[item.activity.activity_id for item in canceled],
                    )
                if discarded_deferred:
                    self._trace_logger.info(
                        "runtime_coordinator:user_input:deferred_autonomous_discarded",
                        event_id=prioritized_event.event_id,
                        activity_ids=[
                            activity.activity_id for activity in discarded_deferred
                        ],
                        reason="restart_with_fresh_context_after_conversation",
                    )
            if prepared_activity is not None:
                self._agent_life_service.sync_from_activity_manager()
                self._trace_logger.info(
                    "runtime_coordinator:user_input:conversation_prepared",
                    event_id=prioritized_event.event_id,
                    activity_id=prepared_activity.activity_id,
                    activity_type=prepared_activity.activity_type.value,
                )
"""
    new = """            foreground_before_input = (
                foreground_at_receipt
                if prioritized_event.event_type == AgentEventType.USER_TEXT
                else self._activity_manager.foreground_activity
            )
            self._user_input_interruption_coordinator.after_prioritization(
                prioritized_event,
                foreground_at_receipt=foreground_before_input,
            )
"""
    text = replace_once(text, old, new)

    if "cancel_inflight_autonomous(" in text[text.index("async def publish_events"):text.index("def _record_conversation_input")]:
        raise RuntimeError("publish_eventsに旧割り込み処理が残っています。")
    TARGET.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
