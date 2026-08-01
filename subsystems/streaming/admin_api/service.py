"""Streaming-only Admin application service and read-model projector."""

from __future__ import annotations

from collections import deque
from typing import Any
from uuid import uuid4

from app.integrations.streaming import (
    CURRENT_STREAMING_API_VERSION,
    StreamingEventEnvelope,
    StreamingEventType,
)
from subsystems.streaming.admin_api.models import (
    StreamingAdminApiError,
    to_json,
    utc_now,
)
from subsystems.streaming.api import StreamingSubsystemApi
from subsystems.streaming.domain import (
    ApproveNormalStreamEndCommand,
    ApproveStreamStartCommand,
    EmergencyStopStreamCommand,
    RetryCommentResponseCommand,
    RetryMainSegmentCommand,
    RetryOpeningCommand,
    StreamPreparationCommand,
)
from subsystems.streaming.ports.comment_events import StreamingCommentIngressEvent


class StreamingAdminService:
    """Project Subsystem state for operators without importing Core Runtime."""

    def __init__(self, subsystem: StreamingSubsystemApi) -> None:
        self.subsystem = subsystem
        self._events: deque[StreamingEventEnvelope] = deque(maxlen=256)
        self._settings: dict[str, object] = {
            "obs_auto_refresh": True,
            "obs_refresh_interval": 30,
            "youtube_auto_refresh": True,
            "youtube_refresh_interval": 30,
            "stale_threshold_seconds": 60,
            "event_coalescing_ms": 250,
            "log_verbosity": "info",
        }

    async def health(self) -> dict[str, Any]:
        health = await self.subsystem.get_health()
        return {
            "status": "available" if health.healthy else "degraded",
            "subsystem_version": "1.0.0",
            "api_version": str(CURRENT_STREAMING_API_VERSION),
            "observed_at": to_json(health.checked_at),
            "configuration_loaded": True,
            "event_stream_available": True,
            "subsystem_health": to_json(health),
            "manual_check_log": {"enabled": False},
        }

    async def status(self) -> dict[str, Any]:
        return {
            "status": to_json(await self.subsystem.get_status()),
            "observed_at": to_json(utc_now()),
        }

    async def capabilities(self) -> dict[str, Any]:
        capabilities = await self.subsystem.get_capabilities()
        values = sorted(item.value for item in capabilities.values)
        return {
            "items": [{"capability": value, "available": True, "reason": None} for value in values],
            "values": values,
        }

    async def dependency_health(self) -> dict[str, Any]:
        values = [to_json(item) for item in await self.subsystem.list_dependency_health()]
        components = self.subsystem.sessions
        values.extend(
            (
                {
                    "kind": "core_content_execution",
                    "state": (
                        "ready" if components.content_execution_connected else "disconnected"
                    ),
                    "healthy": components.content_execution_connected,
                    "available": components.content_execution_connected,
                    "checked_at": to_json(utc_now()),
                    "message": (
                        None
                        if components.content_execution_connected
                        else "core_content_execution_not_connected"
                    ),
                },
                {
                    "kind": "core_comment_decision",
                    "state": (
                        "ready" if components.core_comment_decision is not None else "disconnected"
                    ),
                    "healthy": components.core_comment_decision is not None,
                    "available": components.core_comment_decision is not None,
                    "checked_at": to_json(utc_now()),
                    "message": (
                        None
                        if components.core_comment_decision is not None
                        else "core_comment_decision_not_connected"
                    ),
                },
            )
        )
        return {"items": values}

    async def auth_status(self) -> dict[str, Any]:
        return to_json(await self.subsystem.sessions.prepare.get_youtube_authentication_state())

    async def start_auth(self, command_id: str) -> dict[str, Any]:
        self._required(command_id, "command_id")
        result = await self.subsystem.sessions.prepare.authenticate_youtube()
        self._emit("youtube.authentication_changed", command_id)
        return {"command_id": command_id, "accepted": True, "state": to_json(result)}

    async def broadcasts(self) -> dict[str, Any]:
        return {"items": to_json(await self.subsystem.sessions.prepare.list_broadcasts())}

    def run_of_shows(self) -> dict[str, Any]:
        return {"items": to_json(self.subsystem.sessions.prepare.list_run_of_shows())}

    def session(self) -> dict[str, Any]:
        value = self.subsystem.sessions.prepare.find_active_session()
        if value is None:
            raise StreamingAdminApiError(
                "stream.session.not_found", "stream session not found", 404
            )
        return to_json(value)

    async def prepare(self, payload: dict[str, Any]) -> dict[str, Any]:
        command_id = self._string(payload, "command_id")
        broadcast_id = self._string(payload, "broadcast_id")
        run_of_show_id = self._string(payload, "run_of_show_id")
        broadcasts = await self.subsystem.sessions.prepare.list_broadcasts()
        broadcast = next((item for item in broadcasts if item.broadcast_id == broadcast_id), None)
        if broadcast is None:
            raise StreamingAdminApiError("youtube.broadcast.not_found", "broadcast not found", 404)
        session_id = payload.get("session_id")
        session = (
            self.subsystem.sessions.prepare.get_session(str(session_id)) if session_id else None
        )
        trace_id = str(payload.get("trace_id") or uuid4())
        if session is None:
            session = self.subsystem.sessions.prepare.create_session(
                broadcast,
                trace_id=trace_id,
                run_of_show_id=run_of_show_id,
            )
        expected = payload.get("expected_state_version")
        if expected is not None and int(expected) != session.state_version:
            raise StreamingAdminApiError(
                "stream.prepare.version_mismatch", "state version mismatch", 409
            )
        result = await self.subsystem.sessions.prepare.execute(
            StreamPreparationCommand(
                command_id=command_id,
                trace_id=trace_id,
                session_id=session.session_id,
                selected_broadcast_id=broadcast_id,
                expected_state_version=session.state_version,
                run_of_show_id=run_of_show_id,
            )
        )
        self._emit("session.changed", trace_id, {"session_id": session.session_id})
        return to_json(result)

    async def obs_status(self) -> dict[str, Any]:
        checks = await self.subsystem.sessions.prepare.inspect_obs()
        return {
            "status": (
                "ready"
                if checks and all(item.status.value == "healthy" for item in checks)
                else "degraded"
            ),
            "adapter_type": self.subsystem.sessions.prepare.obs_adapter_type,
            "checks": to_json(checks),
            "observed_at": to_json(utc_now()),
        }

    async def approve_start(self, payload: dict[str, Any]) -> dict[str, Any]:
        command = ApproveStreamStartCommand(
            self._string(payload, "command_id"),
            str(payload.get("trace_id") or uuid4()),
            self._string(payload, "session_id"),
            self._integer(payload, "expected_state_version"),
            self._string(payload, "approved_by"),
        )
        result = await self.subsystem.sessions.start.execute(command)
        self._emit("session.changed", command.trace_id, {"session_id": command.session_id})
        return to_json(result)

    def start_status(self) -> dict[str, Any]:
        value = self.subsystem.sessions.start.latest_result
        return self._found(value, "stream.start.not_found", "stream start result not found")

    def opening_status(self) -> dict[str, Any]:
        session = self._session_value()
        return self._found(
            self.subsystem.sessions.opening.status(session.session_id),
            "opening.not_found",
            "opening not found",
        )

    async def retry_opening(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = await self.subsystem.sessions.opening.retry(
            RetryOpeningCommand(
                self._string(payload, "command_id"),
                self._string(payload, "session_id"),
                self._integer(payload, "expected_activity_version"),
            )
        )
        self._emit("segment.changed", result.trace_id)
        return to_json(result)

    def main_status(self) -> dict[str, Any]:
        session = self._session_value()
        return self._found(
            self.subsystem.sessions.main_segment.status(session.session_id),
            "main_segment.not_found",
            "main segment not found",
        )

    async def retry_main(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = await self.subsystem.sessions.main_segment.retry(
            RetryMainSegmentCommand(
                self._string(payload, "command_id"),
                self._string(payload, "session_id"),
                self._string(payload, "activity_id"),
                self._integer(payload, "expected_activity_version"),
            )
        )
        self._emit("segment.changed", result.trace_id)
        return to_json(result)

    async def approve_end(self, payload: dict[str, Any]) -> dict[str, Any]:
        command = ApproveNormalStreamEndCommand(
            self._string(payload, "command_id"),
            str(payload.get("trace_id") or uuid4()),
            self._string(payload, "session_id"),
            self._integer(payload, "expected_state_version"),
            self._string(payload, "approved_by"),
        )
        result = await self.subsystem.sessions.end.normal(command)
        self._emit("session.changed", command.trace_id)
        return to_json(result)

    async def emergency_stop(self, payload: dict[str, Any]) -> dict[str, Any]:
        command = EmergencyStopStreamCommand(
            self._string(payload, "command_id"),
            str(payload.get("trace_id") or uuid4()),
            self._string(payload, "session_id"),
            self._integer(payload, "expected_state_version"),
            self._string(payload, "requested_by"),
            self._string(payload, "reason_code"),
        )
        result = await self.subsystem.sessions.end.emergency(command)
        self._emit("session.changed", command.trace_id)
        return to_json(result)

    def end_status(self) -> dict[str, Any]:
        return self._found(
            self.subsystem.sessions.end.latest_result,
            "stream.end.not_found",
            "end result not found",
        )

    def lifecycle(self) -> dict[str, Any]:
        session = self._session_value()
        return self.subsystem.sessions.lifecycle.snapshot(session.session_id)

    def comments_status(self) -> dict[str, Any]:
        session = self._session_value()
        return {
            "session_id": session.session_id,
            "moderation": to_json(self.subsystem.sessions.moderation.status(session.session_id)),
            "ranking": to_json(self.subsystem.sessions.ranking.status(session.session_id)),
            "response": to_json(self.subsystem.sessions.response.status(session.session_id)),
        }

    def moderation_status(self) -> dict[str, Any]:
        session = self._session_value()
        return to_json(self.subsystem.sessions.moderation.status(session.session_id))

    def moderation_recent(self) -> dict[str, Any]:
        session = self._session_value()
        return {"items": to_json(self.subsystem.sessions.moderation.recent(session.session_id))}

    def ranking_status(self) -> dict[str, Any]:
        session = self._session_value()
        return to_json(self.subsystem.sessions.ranking.status(session.session_id))

    def ranking_top(self) -> dict[str, Any]:
        session = self._session_value()
        return {"items": to_json(self.subsystem.sessions.ranking.top(session.session_id))}

    def current_selection(self) -> dict[str, Any]:
        session = self._session_value()
        return {
            "selection": to_json(
                self.subsystem.sessions.ranking.current_selection(session.session_id)
            )
        }

    def response_status(self) -> dict[str, Any]:
        session = self._session_value()
        return self._found(
            self.subsystem.sessions.response.status(session.session_id),
            "comment_response.not_found",
            "comment response not found",
        )

    def response_recent(self) -> dict[str, Any]:
        session = self._session_value()
        return {"items": to_json(self.subsystem.sessions.response.recent(session.session_id))}

    async def retry_response(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = await self.subsystem.sessions.response.retry(
            RetryCommentResponseCommand(
                self._string(payload, "command_id"),
                self._string(payload, "session_id"),
                self._string(payload, "activity_id"),
                self._string(payload, "selection_id"),
                self._integer(payload, "expected_activity_version"),
            )
        )
        self._emit("comment.response_changed", result.trace_id)
        return to_json(result)

    async def demo_comment(self, payload: dict[str, Any]) -> dict[str, Any]:
        session = self._session_value()
        text = self._string(payload, "text")
        event = StreamingCommentIngressEvent(
            "youtube_comment",
            {
                "session_id": session.session_id,
                "message_id": str(payload.get("test_case_id") or uuid4()),
                "comment": text,
                "message_type": "paid" if payload.get("is_paid") else "text",
                "is_paid": bool(payload.get("is_paid")),
                "author": {
                    "channel_id": "demo-viewer",
                    "display_name": str(payload.get("author_name") or "Demo Viewer"),
                },
                "published_at": to_json(utc_now()),
            },
        )
        decision = await self.subsystem.sessions.moderation.evaluate_event(event)
        self._emit("comment.received", event.trace_id, {"session_id": session.session_id})
        return {"accepted": decision is not None, "decision": to_json(decision)}

    async def console(self) -> dict[str, Any]:
        status = await self.subsystem.get_status()
        session = self.subsystem.sessions.prepare.find_active_session()
        dependencies = await self.dependency_health()
        session_status = session.status.value if session is not None else "none"
        return {
            "generated_at": to_json(utc_now()),
            "current_state": session_status if session is not None else status.value,
            "current_message": self._message(session_status),
            "subsystem_state": status.value,
            "runtime_state": status.value,
            "services": dependencies["items"],
            "dependency_health": dependencies["items"],
            "adapter_capabilities": (await self.capabilities())["items"],
            "operator_action": self._operator_action(session_status),
            "lifecycle_steps": self._lifecycle_steps(session_status),
            "responsibilities": self._responsibilities(),
            "timeline": [to_json(item) for item in self._combined_events()[-20:]],
            "comments": self.comments_status() if session is not None else None,
            "lifecycle": (
                self.subsystem.sessions.lifecycle.snapshot(session.session_id)
                if session is not None
                else None
            ),
            "settings": dict(self._settings),
            "log_settings": dict(self._settings),
        }

    async def diagnostics(self) -> dict[str, Any]:
        return {
            "generated_at": to_json(utc_now()),
            "subsystem_status": to_json(await self.subsystem.get_status()),
            "dependency_health": (await self.dependency_health())["items"],
            "session": (
                to_json(value)
                if (value := self.subsystem.sessions.prepare.find_active_session())
                else None
            ),
            "recent_events": [to_json(item) for item in self._combined_events()[-50:]],
            "configuration_summary": {"loaded": True},
            "event_cursor": (
                self._combined_events()[-1].event_id if self._combined_events() else None
            ),
        }

    def settings(self) -> dict[str, object]:
        return dict(self._settings)

    def update_settings(self, payload: dict[str, Any]) -> dict[str, object]:
        unknown = set(payload) - set(self._settings)
        if unknown:
            raise StreamingAdminApiError("settings.invalid", "unsupported setting", 422)
        for key, value in payload.items():
            if key.endswith("interval") or key.endswith("seconds") or key.endswith("ms"):
                if not isinstance(value, (int, float)) or value <= 0:
                    raise StreamingAdminApiError(
                        "settings.invalid", "interval must be positive", 422
                    )
            self._settings[key] = value
        return dict(self._settings)

    async def events_after(self, event_id: str | None) -> tuple[StreamingEventEnvelope, ...]:
        events = self._combined_events(await self.subsystem.read_events())
        if event_id is None:
            return tuple(events)
        position = next(
            (index for index, event in enumerate(events) if event.event_id == event_id),
            None,
        )
        return tuple(events[position + 1 :]) if position is not None else ()

    def _combined_events(self, public: object = ()) -> list[StreamingEventEnvelope]:
        values = [*list(public), *self.subsystem.sessions.public_comment_events, *self._events]
        unique = {item.event_id: item for item in values}
        return sorted(unique.values(), key=lambda item: item.occurred_at)[-256:]

    def _emit(
        self,
        event_type: str,
        correlation_id: str,
        payload: dict[str, object] | None = None,
    ) -> None:
        self._events.append(
            StreamingEventEnvelope(
                event_id=str(uuid4()),
                event_type=StreamingEventType.OPERATION_COMPLETED,
                occurred_at=utc_now(),
                api_version=CURRENT_STREAMING_API_VERSION,
                correlation_id=correlation_id,
                payload={"event_name": event_type, **(payload or {})},
            )
        )

    def _session_value(self) -> object:
        value = self.subsystem.sessions.prepare.find_active_session()
        if value is None:
            raise StreamingAdminApiError(
                "stream.session.not_found", "stream session not found", 404
            )
        return value

    @staticmethod
    def _found(value: object, code: str, message: str) -> dict[str, Any]:
        if value is None:
            raise StreamingAdminApiError(code, message, 404)
        return to_json(value)

    @staticmethod
    def _required(value: object, name: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise StreamingAdminApiError("request.invalid", f"{name} is required", 422)

    @classmethod
    def _string(cls, payload: dict[str, Any], name: str) -> str:
        value = payload.get(name)
        cls._required(value, name)
        return str(value)

    @staticmethod
    def _integer(payload: dict[str, Any], name: str) -> int:
        value = payload.get(name)
        if isinstance(value, bool) or not isinstance(value, int):
            raise StreamingAdminApiError("request.invalid", f"{name} must be an integer", 422)
        return value

    @staticmethod
    def _message(status: str) -> str:
        return {
            "none": "配信Sessionはありません。",
            "ready": "配信開始の承認待ちです。",
            "live": "配信中です。",
            "completed": "配信は終了しました。",
        }.get(status, f"配信状態: {status}")

    @staticmethod
    def _operator_action(status: str) -> dict[str, object]:
        action = {
            "none": ("prepare", "配信を準備"),
            "ready": ("start", "配信開始を承認"),
            "live": ("end", "配信終了を承認"),
        }.get(status)
        return {
            "action": action[0] if action else None,
            "label": action[1] if action else "操作はありません",
            "required": action is not None,
        }

    @staticmethod
    def _lifecycle_steps(current: str) -> list[dict[str, object]]:
        order = ("created", "preparing", "ready", "live", "completed")
        current_index = order.index(current) if current in order else -1
        return [
            {
                "title": value,
                "status": (
                    "completed"
                    if index < current_index
                    else "current"
                    if index == current_index
                    else "pending"
                ),
                "owner": "streaming_subsystem",
                "block_reason": None,
                "error_code": None,
            }
            for index, value in enumerate(order)
        ]

    @staticmethod
    def _responsibilities() -> list[dict[str, str]]:
        return [
            {"operation": "stream control", "owner": "streaming_subsystem", "status": "active"},
            {"operation": "content execution", "owner": "core", "status": "optional"},
        ]
