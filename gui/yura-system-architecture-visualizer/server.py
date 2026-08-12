from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from dependency_graph import build_graph

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
WEB_ROOT = HERE / "web"

app = FastAPI(title="Yura System Architecture Visualizer")
app.mount("/static", StaticFiles(directory=WEB_ROOT), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_ROOT / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/graph")
def graph() -> dict[str, object]:
    return build_graph(REPO_ROOT)


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8765")),
    )
