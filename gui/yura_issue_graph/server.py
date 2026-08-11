from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from .config import IssueGraphConfig
from .github_client import GitHubApiError, IssueGraphService

_STATIC_DIR = Path(__file__).with_name("static")
_INDEX_HTML = _STATIC_DIR / "index.html"

app = FastAPI(title="Yura Issue Graph", version="1.0.0")


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(_INDEX_HTML.read_text(encoding="utf-8"))


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "yura-issue-graph"}


@app.get("/api/graph")
async def graph() -> dict[str, object]:
    config = IssueGraphConfig.from_env()
    service = IssueGraphService(config)
    try:
        return await asyncio.to_thread(service.load_graph)
    except GitHubApiError as error:
        raise HTTPException(status_code=502, detail=error.public_message) from error
