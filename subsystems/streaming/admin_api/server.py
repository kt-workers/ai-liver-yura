"""FastAPI transport for the standalone Streaming Subsystem Admin API."""

from __future__ import annotations

import asyncio
import hmac
import json
import os
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse

from subsystems.streaming.admin_api.models import StreamingAdminApiError, to_json
from subsystems.streaming.admin_api.service import StreamingAdminService
from subsystems.streaming.api import StreamingSubsystemApi
from subsystems.streaming.api.http_routes import create_streaming_public_router


def _error(
    code: str,
    message: str,
    status: int,
    *,
    retryable: bool = False,
) -> JSONResponse:
    return JSONResponse(
        {
            "error": {
                "code": code,
                "message": message,
                "retryable": retryable,
                "trace_id": str(uuid4()),
            }
        },
        status_code=status,
    )


def create_streaming_admin_api(
    subsystem_api: StreamingSubsystemApi,
    *,
    token: str | None = None,
) -> FastAPI:
    """Create an import-safe Admin API without starting Core or external I/O."""

    service = StreamingAdminService(subsystem_api)
    app = FastAPI(title="Streaming Subsystem Admin API", version="1.0.0")
    configured_token = (
        token if token is not None else os.getenv("STREAMING_SUBSYSTEM_ADMIN_API_TOKEN")
    )
    app.state.streaming_admin_service = service
    app.include_router(create_streaming_public_router(subsystem_api))

    @app.middleware("http")
    async def authenticate(request: Request, call_next: Any) -> Any:
        if configured_token:
            supplied = request.headers.get("authorization", "")
            expected = f"Bearer {configured_token}"
            if not hmac.compare_digest(supplied, expected):
                return _error("request.unauthorized", "invalid admin API token", 401)
        return await call_next(request)

    @app.exception_handler(StreamingAdminApiError)
    async def admin_error(_: Request, error: StreamingAdminApiError) -> JSONResponse:
        return _error(
            error.code,
            str(error),
            error.status_code,
            retryable=error.retryable,
        )

    @app.exception_handler(ValueError)
    async def value_error(_: Request, error: ValueError) -> JSONResponse:
        message = str(error)
        status = 404 if "not_found" in message else 409 if "version" in message else 422
        return _error(
            message if "." in message else "request.invalid",
            "request rejected",
            status,
        )

    @app.exception_handler(RuntimeError)
    async def runtime_error(_: Request, error: RuntimeError) -> JSONResponse:
        code = str(getattr(error, "code", str(error) or "streaming.operation_failed"))
        status = 404 if code.endswith("not_found") else 409
        return _error(code, "streaming operation rejected", status)

    @app.get("/api/v1/health")
    async def health() -> dict[str, Any]:
        return await service.health()

    @app.get("/api/v1/status")
    async def status() -> dict[str, Any]:
        return await service.status()

    @app.get("/api/v1/capabilities")
    async def capabilities() -> dict[str, Any]:
        return await service.capabilities()

    @app.get("/api/v1/dependencies/health")
    async def dependency_health() -> dict[str, Any]:
        return await service.dependency_health()

    @app.get("/api/v1/youtube/auth")
    async def youtube_auth() -> dict[str, Any]:
        return await service.auth_status()

    @app.post("/api/v1/youtube/auth/start", status_code=202)
    async def youtube_auth_start(payload: dict[str, Any]) -> dict[str, Any]:
        return await service.start_auth(str(payload.get("command_id") or ""))

    @app.get("/api/v1/streaming/broadcasts")
    async def broadcasts() -> dict[str, Any]:
        return await service.broadcasts()

    @app.post("/api/v1/streaming/broadcasts/refresh")
    async def refresh_broadcasts() -> dict[str, Any]:
        return await service.broadcasts()

    @app.get("/api/v1/streaming/run-of-shows")
    async def run_of_shows() -> dict[str, Any]:
        return service.run_of_shows()

    @app.get("/api/v1/streaming/session")
    async def session() -> dict[str, Any]:
        return service.session()

    @app.post("/api/v1/streaming/session/prepare")
    async def prepare(payload: dict[str, Any]) -> dict[str, Any]:
        return await service.prepare(payload)

    @app.get("/api/v1/obs/status")
    async def obs_status() -> dict[str, Any]:
        return await service.obs_status()

    @app.post("/api/v1/obs/refresh")
    async def obs_refresh() -> dict[str, Any]:
        return await service.obs_status()

    @app.post("/api/v1/streaming/session/start/approve", status_code=202)
    async def approve_start(payload: dict[str, Any]) -> dict[str, Any]:
        return await service.approve_start(payload)

    @app.get("/api/v1/streaming/session/start/status")
    async def start_status() -> dict[str, Any]:
        return service.start_status()

    @app.get("/api/v1/streaming/session/opening")
    async def opening_status() -> dict[str, Any]:
        return service.opening_status()

    @app.post("/api/v1/streaming/session/opening/retry")
    async def retry_opening(payload: dict[str, Any]) -> dict[str, Any]:
        return await service.retry_opening(payload)

    @app.get("/api/v1/streaming/session/main-segment")
    async def main_status() -> dict[str, Any]:
        return service.main_status()

    @app.post("/api/v1/streaming/session/main-segment/retry")
    async def retry_main(payload: dict[str, Any]) -> dict[str, Any]:
        return await service.retry_main(payload)

    @app.post("/api/v1/streaming/session/end/approve")
    async def approve_end(payload: dict[str, Any]) -> dict[str, Any]:
        return await service.approve_end(payload)

    @app.post("/api/v1/streaming/session/emergency-stop")
    async def emergency_stop(payload: dict[str, Any]) -> dict[str, Any]:
        return await service.emergency_stop(payload)

    @app.get("/api/v1/streaming/session/end/status")
    async def end_status() -> dict[str, Any]:
        return service.end_status()

    @app.get("/api/v1/streaming/session/lifecycle")
    async def lifecycle() -> dict[str, Any]:
        return service.lifecycle()

    @app.get("/api/v1/streaming/session/comments/status")
    async def comments_status() -> dict[str, Any]:
        return service.comments_status()

    @app.post("/api/v1/streaming/session/comments/refresh-status")
    async def refresh_comments_status() -> dict[str, Any]:
        return service.comments_status()

    @app.get("/api/v1/streaming/session/comments/moderation/status")
    async def moderation_status() -> dict[str, Any]:
        return service.moderation_status()

    @app.get("/api/v1/streaming/session/comments/moderation/recent")
    async def moderation_recent() -> dict[str, Any]:
        return service.moderation_recent()

    @app.get("/api/v1/streaming/session/comments/ranking/status")
    async def ranking_status() -> dict[str, Any]:
        return service.ranking_status()

    @app.get("/api/v1/streaming/session/comments/ranking/top")
    async def ranking_top() -> dict[str, Any]:
        return service.ranking_top()

    @app.get("/api/v1/streaming/session/comments/selection/current")
    async def selection() -> dict[str, Any]:
        return service.current_selection()

    @app.get("/api/v1/streaming/session/comments/response/status")
    async def response_status() -> dict[str, Any]:
        return service.response_status()

    @app.get("/api/v1/streaming/session/comments/response/recent")
    async def response_recent() -> dict[str, Any]:
        return service.response_recent()

    @app.post("/api/v1/streaming/session/comments/response/retry")
    async def retry_response(payload: dict[str, Any]) -> dict[str, Any]:
        return await service.retry_response(payload)

    @app.post("/api/v1/demo/live-chat/messages", status_code=202)
    async def demo_comment(payload: dict[str, Any]) -> dict[str, Any]:
        return await service.demo_comment(payload)

    @app.get("/api/v1/admin/console")
    async def console() -> dict[str, Any]:
        return await service.console()

    @app.get("/api/v1/admin/diagnostics")
    async def diagnostics() -> dict[str, Any]:
        return await service.diagnostics()

    @app.post("/api/v1/admin/diagnostics/save")
    async def save_diagnostics() -> dict[str, Any]:
        return {"saved": False, "reason": "filesystem_export_disabled"}

    @app.get("/api/v1/admin/settings")
    async def settings() -> dict[str, object]:
        return service.settings()

    @app.patch("/api/v1/admin/settings")
    async def update_settings(payload: dict[str, Any]) -> dict[str, object]:
        return {"applied": True, "settings": service.update_settings(payload)}

    async def event_stream(
        last_event_id: str | None,
    ) -> StreamingResponse:
        async def generate() -> AsyncIterator[str]:
            cursor = last_event_id
            while True:
                events = await service.events_after(cursor)
                if events:
                    for event in events:
                        cursor = event.event_id
                        payload = json.dumps(to_json(event), separators=(",", ":"))
                        yield (
                            f"id: {event.event_id}\n"
                            f"event: {event.event_type.value}\n"
                            f"data: {payload}\n\n"
                        )
                else:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform"},
        )

    @app.get("/api/v1/events")
    async def events(
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        return await event_stream(last_event_id)

    @app.get("/api/v1/events/stream", include_in_schema=False)
    async def events_compat(
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        return await event_stream(last_event_id)

    return app
