from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from app.domain.activities import OngoingActivity
from app.domain.character_response import (
    ActivityExecutionResult,
    ActivityExecutionStatus,
)
from app.runtime.ongoing_activity_coordinator import OngoingActivityCoordinator
from app.shared.contracts.plugins.runtime import (
    PluginActivityState,
    PluginActivityStatus,
)
from app.utils.trace import TraceLogger


class PluginSessionBridge(Protocol):
    plugin_id: str

    def snapshot(self) -> Mapping[str, object]: ...

    def link_ongoing_activity(self, ongoing_activity_id: str) -> None: ...

    def rollback_active_session(self, reason: str) -> None: ...


class PluginActivitySynchronizationError(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class PluginOngoingActivitySynchronizer:
    """Plugin SessionとCore OngoingActivityを原子的に同期する。"""

    def __init__(
        self,
        *,
        ongoing_activity_coordinator: OngoingActivityCoordinator,
        trace_logger: TraceLogger,
    ) -> None:
        self._ongoing = ongoing_activity_coordinator
        self._trace_logger = trace_logger

    def begin_turn(
        self,
        *,
        plugin: object,
        operation: str,
        input_text: str,
        source_event_id: str,
        constraints: dict[str, object],
    ) -> None:
        context = self.session_context(plugin)
        plugin_id = str(getattr(plugin, "plugin_id", ""))
        try:
            ongoing = self._ongoing.verify_context(
                session_id=self.optional_context_str(context, "session_id"),
                plugin_id=plugin_id,
            )
            if ongoing is None:
                raise RuntimeError("継続対象のOngoingActivityがありません。")
            ongoing_constraints = ongoing.context.get("constraints", constraints)
            self._ongoing.begin_turn(
                input_text=input_text,
                source_event_id=source_event_id,
                operation=operation,
                constraints=(
                    ongoing_constraints
                    if isinstance(ongoing_constraints, dict)
                    else constraints
                ),
            )
        except RuntimeError as error:
            self._trace_logger.error(
                "runtime_coordinator:ongoing_activity_sync_rejected",
                plugin_id=plugin_id,
                operation=operation,
                reason=str(error),
            )
            self.rollback(plugin, reason="ongoing_activity_context_mismatch")
            raise PluginActivitySynchronizationError(
                "ongoing_activity_context_mismatch"
            ) from error

    def synchronize(
        self,
        *,
        plugin: object,
        activity_state: PluginActivityState,
        request_context: dict[str, object],
        activity_kind: str,
        activity_type: str,
        response_text: str,
        capability: str | None,
        operation: str,
        constraints: dict[str, object],
        goal: str,
        input_text: str,
        source_event_id: str,
        turn_started: bool,
    ) -> tuple[ActivityExecutionResult, OngoingActivity]:
        plugin_id = str(
            request_context.get("plugin_id") or getattr(plugin, "plugin_id", "")
        )
        session_id = activity_state.session_id
        session_status = activity_state.status
        is_terminal = session_status in {
            PluginActivityStatus.COMPLETED,
            PluginActivityStatus.CANCELED,
        }
        execution_result = ActivityExecutionResult(
            activity_type=activity_type,
            operation=operation,
            status=self._execution_status(session_status),
            capability=capability,
            provider=plugin_id,
            payload={
                "summary": response_text,
                "activity_kind": activity_kind,
                "ongoing": not is_terminal,
            },
            constraints=dict(constraints),
        )
        context_updates = {
            "plugin_id": plugin_id,
            "capability": capability,
            "plugin_session_id": session_id,
            "plugin_state_version": request_context.get("plugin_state_version"),
            "plugin_activity_status": session_status.value,
            "constraints": dict(constraints),
        }
        if operation == "start":
            try:
                ongoing = self._ongoing.start(
                    activity_type=activity_type,
                    goal=goal,
                    expected_input=activity_state.expected_input,
                    end_condition=activity_state.end_condition,
                    context=context_updates,
                    input_text=input_text,
                    source_event_id=source_event_id,
                    operation=operation,
                    constraints=constraints,
                )
                linker = getattr(plugin, "link_ongoing_activity", None)
                if not callable(linker):
                    raise RuntimeError(
                        "PluginがOngoingActivity関連付けに対応していません。"
                    )
                linker(ongoing.ongoing_activity_id)
                context_updates["ongoing_activity_id"] = ongoing.ongoing_activity_id
            except Exception:
                self.rollback(plugin, reason="ongoing_activity_start_failed")
                raise
        else:
            verified = self._ongoing.verify_context(
                session_id=session_id,
                plugin_id=plugin_id,
            )
            if verified is None or not turn_started:
                raise PluginActivitySynchronizationError(
                    "plugin_continuation_turn_not_started"
                )
            ongoing = verified
            context_updates["ongoing_activity_id"] = verified.ongoing_activity_id

        recorded = self._ongoing.record_execution(
            execution_result,
            context_updates=context_updates,
            expected_input="" if is_terminal else activity_state.expected_input,
            waiting_input=session_status == PluginActivityStatus.WAITING_INPUT,
        )
        if session_status == PluginActivityStatus.COMPLETED:
            recorded = (
                self._ongoing.complete(reason="plugin_session_completed") or recorded
            )
        elif session_status == PluginActivityStatus.CANCELED:
            recorded = (
                self._ongoing.cancel(reason="plugin_session_canceled") or recorded
            )
        elif session_status == PluginActivityStatus.SUSPENDED:
            recorded = self._ongoing.pause(reason="plugin_session_paused") or recorded
        self._trace_logger.info(
            "runtime_coordinator:plugin_ongoing_activity_synchronized",
            plugin_id=plugin_id,
            ongoing_activity_id=recorded.ongoing_activity_id,
            session_id=session_id,
            operation=operation,
            ongoing_status=recorded.status.value,
            session_status=session_status.value,
            activity_turn_id=recorded.turns[-1].turn_id if recorded.turns else None,
        )
        return execution_result, recorded

    def record_failed_turn(
        self,
        *,
        activity_type: str,
        operation: str,
        capability: str | None,
        plugin_id: str,
        reason: str,
        constraints: dict[str, object],
        conversation_context: dict[str, object],
        activity_state: PluginActivityState | None,
    ) -> None:
        result = ActivityExecutionResult(
            activity_type=activity_type,
            operation=operation,
            status=ActivityExecutionStatus.FAILED,
            capability=capability,
            provider=plugin_id,
            payload={"summary": reason},
            failure_reason=reason,
            constraints=constraints,
        )
        can_continue = (
            activity_state is not None
            and activity_state.status
            in {
                PluginActivityStatus.WAITING_INPUT,
                PluginActivityStatus.SUSPENDED,
            }
        )
        context = dict(conversation_context)
        if activity_state is not None:
            context.update(
                {
                    "plugin_session_id": activity_state.session_id,
                    "plugin_activity_status": activity_state.status.value,
                }
            )
        self._ongoing.record_execution(
            result,
            context_updates=context,
            expected_input=(
                activity_state.expected_input
                if can_continue and activity_state is not None
                else ""
            ),
            waiting_input=can_continue,
        )
        if not can_continue:
            self._ongoing.cancel(reason=reason)

    def rollback(self, plugin: object, *, reason: str) -> None:
        self._ongoing.cancel(reason=reason)
        rollback = getattr(plugin, "rollback_active_session", None)
        if callable(rollback):
            rollback(reason)
        self._trace_logger.warning(
            "runtime_coordinator:plugin_ongoing_activity_rolled_back",
            plugin_id=getattr(plugin, "plugin_id", None),
            reason=reason,
        )

    @staticmethod
    def session_context(plugin: object) -> dict[str, object]:
        snapshot = getattr(plugin, "snapshot", None)
        value = snapshot() if callable(snapshot) else {}
        return dict(value) if isinstance(value, Mapping) else {}

    @staticmethod
    def optional_context_str(
        context: dict[str, object],
        key: str,
    ) -> str | None:
        value = context.get(key)
        return str(value) if value is not None else None

    @staticmethod
    def _execution_status(
        status: PluginActivityStatus,
    ) -> ActivityExecutionStatus:
        if status == PluginActivityStatus.CANCELED:
            return ActivityExecutionStatus.CANCELED
        if status == PluginActivityStatus.COMPLETED:
            return ActivityExecutionStatus.SUCCEEDED
        return ActivityExecutionStatus.WAITING_INPUT
