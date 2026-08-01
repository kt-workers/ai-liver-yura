"""HTTP routes for the versioned Streaming public integration contract."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.integrations.streaming import CURRENT_STREAMING_API_VERSION, StreamingCursor
from app.integrations.streaming.wire import parse_operation_request, to_wire
from subsystems.streaming.api.subsystem_api import StreamingSubsystemApi


def create_streaming_public_router(api: StreamingSubsystemApi) -> APIRouter:
    router = APIRouter(prefix="/api/v1/integration", tags=["streaming-integration"])

    @router.get("/version")
    async def version() -> Any:
        return to_wire(CURRENT_STREAMING_API_VERSION)

    @router.get("/status")
    async def status() -> dict[str, object]:
        return {"status": to_wire(await api.get_status())}

    @router.get("/health")
    async def health() -> Any:
        return to_wire(await api.get_health())

    @router.get("/capabilities")
    async def capabilities() -> Any:
        return to_wire(await api.get_capabilities())

    @router.get("/dependencies/health")
    async def dependency_health() -> dict[str, object]:
        return {"items": to_wire(await api.list_dependency_health())}

    @router.post("/operations")
    async def execute(payload: dict[str, Any]) -> Any:
        return to_wire(await api.execute_operation(parse_operation_request(payload)))

    @router.get("/events")
    async def events(after: str | None = Query(default=None)) -> dict[str, object]:
        cursor = StreamingCursor(after) if after else None
        return {"items": to_wire(await api.read_events(cursor))}

    return router
