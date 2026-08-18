from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field

from app.domain.llm import LLMModelClass, LLMReasoningEffort
from cloud_validation.v2_character_language_gate import CharacterLanguageLabGate
from cloud_validation.v2_character_language_lab import (
    CharacterLanguageLabMode,
    CharacterLanguageLabRequest,
    CharacterLanguageLabService,
    CharacterLanguageLabSettings,
)

_ROOT = Path(__file__).parent
_security = HTTPBasic(auto_error=False)
_settings = CharacterLanguageLabSettings.from_environment()
_engine = CharacterLanguageLabService(_settings)
_service = CharacterLanguageLabGate(_engine)


class RunInput(BaseModel):
    mode: str = "isolation"
    scenario_id: str = "neutral_fact"
    repetitions: int = Field(default=1, ge=1, le=10)
    character_model: str = ""
    character_model_class: str = "balanced"
    character_reasoning_effort: str = "medium"
    semantic_model: str = ""
    semantic_model_class: str = "balanced"
    semantic_reasoning_effort: str = "medium"
    run_semantic_verification: bool = True
    timeout_seconds: float = Field(default=60, gt=0, le=300)
    max_output_tokens: int = Field(default=2400, ge=128, le=12000)


def _auth_expected() -> tuple[str, str]:
    return (
        os.getenv("YURA_LAB_USERNAME", "").strip(),
        os.getenv("YURA_LAB_PASSWORD", ""),
    )


def _require_auth(
    credentials: HTTPBasicCredentials | None = Depends(_security),
) -> None:
    username, password = _auth_expected()
    if not username or not password:
        return
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Basic"},
        )
    username_ok = secrets.compare_digest(credentials.username, username)
    password_ok = secrets.compare_digest(credentials.password, password)
    if not username_ok or not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Basic"},
        )


def _model_class(value: str) -> LLMModelClass:
    try:
        return LLMModelClass(value)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=f"invalid model class: {value}") from error


def _reasoning_effort(value: str) -> LLMReasoningEffort:
    try:
        return LLMReasoningEffort(value)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=f"invalid reasoning effort: {value}") from error


def _workspace_html() -> str:
    html = _ROOT.joinpath("v2_character_language_workspace.html").read_text(
        encoding="utf-8"
    )
    css = _ROOT.joinpath("v2_character_language_workspace.css").read_text(
        encoding="utf-8"
    )
    js = _ROOT.joinpath("v2_character_language_workspace.js").read_text(
        encoding="utf-8"
    )
    return html.replace("__STYLE__", css).replace("__SCRIPT__", js)


def create_app(
    service: CharacterLanguageLabGate | None = None,
) -> FastAPI:
    lab_service = service or _service
    app = FastAPI(title="Yura V2 Character Language Lab")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse, dependencies=[Depends(_require_auth)])
    async def index() -> str:
        return _workspace_html()

    @app.get("/api/readiness", dependencies=[Depends(_require_auth)])
    async def readiness() -> dict[str, object]:
        return lab_service.readiness()

    @app.post("/api/run", dependencies=[Depends(_require_auth)])
    async def run(payload: RunInput) -> dict[str, object]:
        readiness_value = lab_service.readiness()
        character_model = (
            payload.character_model.strip()
            or str(readiness_value.get("default_character_model") or "").strip()
        )
        semantic_model = (
            payload.semantic_model.strip()
            or str(readiness_value.get("default_semantic_model") or "").strip()
        )
        if not character_model:
            raise HTTPException(status_code=422, detail="Character Language modelが未設定です")
        if payload.run_semantic_verification and not semantic_model:
            raise HTTPException(status_code=422, detail="Semantic Verification modelが未設定です")
        try:
            mode = CharacterLanguageLabMode(payload.mode)
        except ValueError as error:
            raise HTTPException(status_code=422, detail="modeが不正です") from error
        request = CharacterLanguageLabRequest(
            mode,
            payload.scenario_id,
            payload.repetitions,
            character_model,
            _model_class(payload.character_model_class),
            _reasoning_effort(payload.character_reasoning_effort),
            semantic_model or character_model,
            _model_class(payload.semantic_model_class),
            _reasoning_effort(payload.semantic_reasoning_effort),
            run_semantic_verification=payload.run_semantic_verification,
            timeout_seconds=payload.timeout_seconds,
            max_output_tokens=payload.max_output_tokens,
        )
        try:
            return await lab_service.run(request)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    return app


app = create_app()

__all__ = ["RunInput", "app", "create_app"]
