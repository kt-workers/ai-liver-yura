"""HTTP adapter for Core-only administration."""

from __future__ import annotations

import hmac
import os
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.admin_api.service import CoreAdminService


def create_admin_api(
    service: CoreAdminService | None = None,
    *,
    token: str | None = None,
) -> FastAPI:
    resolved = service or CoreAdminService()
    configured_token = token if token is not None else os.getenv("YURA_CORE_ADMIN_API_TOKEN")
    app = FastAPI(title="Yura Core Admin API", version="1.0.0")

    @app.middleware("http")
    async def authenticate(request: Request, call_next: Any) -> Any:
        if configured_token:
            supplied = request.headers.get("authorization", "")
            if not hmac.compare_digest(supplied, f"Bearer {configured_token}"):
                return JSONResponse(
                    {"error": {"code": "request.unauthorized"}}, status_code=401
                )
        return await call_next(request)

    @app.get("/api/v1/health")
    async def health() -> dict[str, object]:
        return resolved.health()

    @app.get("/api/v1/diagnostics")
    async def diagnostics() -> dict[str, object]:
        return resolved.diagnostics()

    @app.get("/api/v1/settings")
    async def settings() -> dict[str, object]:
        return resolved.settings()

    @app.get("/api/v1/manual-checks")
    async def manual_checks() -> dict[str, object]:
        return resolved.list_manual_checks()

    @app.post("/api/v1/manual-checks/{check_id}")
    async def run_manual_check(check_id: str) -> Any:
        try:
            return resolved.run_manual_check(check_id)
        except KeyError:
            return JSONResponse(
                {"error": {"code": "manual_check.not_found"}}, status_code=404
            )

    return app
