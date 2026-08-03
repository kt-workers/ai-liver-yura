from __future__ import annotations

import json
import os
import secrets
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Protocol
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field

from app.adapters.llm import OpenAIResponseGenerator
from app.adapters.prompt import SimplePromptBuilder
from app.domain.activities import Activity, ActivityType
from app.domain.character import CharacterProfile
from app.ports.llm_roles import ResponseGeneratorRoleAdapter
from app.prompting import InternalDirectivePromptBuilder
from app.runtime.cognitive_direction_parsers import InputMeaningJsonParser
from app.runtime.cognitive_direction_services import InternalDirectivePlanner

_FALLBACK_RESPONSE = "__YURA_INTERNAL_DIRECTIVE_LAB_PROVIDER_UNAVAILABLE__"
_DEFAULT_CHARACTER_PROFILE: dict[str, object] = {
    "name": "ゆら",
    "personality": "穏やかで好奇心を持つが、相手の意図を優先する",
    "speaking_style": "自然な日本語。必要以上に話題を広げない",
    "existence": {
        "physical_capabilities": ["物理的な身体を持たない"],
        "sensory_capabilities": ["入力として渡された情報だけを知覚する"],
        "experience_boundaries": ["根拠のない現実空間での実体験を語らない"],
        "world_relationship": "デジタル空間からユーザーと会話する存在",
    },
}
_DEFAULT_MEANING: dict[str, object] = {
    "input_speech_act": "question",
    "primary_intent": "ask_current_feeling",
    "expected_response": "direct_answer",
    "target": {"type": "internal_state", "id": "current_feeling"},
    "entities": [],
    "references": [],
    "information_provided": [],
    "negated": False,
    "hypothetical": False,
    "past_reference": False,
    "conversation_phase_signal": "continue",
    "confidence": 0.98,
    "reason": "ユーザーは現在の気分について直接質問している",
}
_DEFAULT_INTERNAL_STATE: dict[str, object] = {
    "emotion": {"joy": 0.58, "calm": 0.74, "amusement": 0.22},
    "drive": {"curiosity": 0.61, "social": 0.55},
    "relationship": {"familiarity": 0.45, "trust": 0.62},
    "motivation": {"engagement": 0.57},
    "moral": {"care": 0.8, "honesty": 0.9},
    "situation": {"current_topic": "現在の気分"},
    "memory": {},
    "related_knowledge": [],
    "last_activity_result": None,
}
_DEFAULT_AVAILABLE_ACTIVITIES: list[dict[str, object]] = [
    {
        "activity_type": "conversation",
        "operations": ["discuss", "explain"],
        "description": "ユーザーとの会話",
    }
]


@dataclass(frozen=True, slots=True)
class LabSettings:
    mode: str
    model: str
    api_key_env: str
    timeout_seconds: float
    username: str
    password: str

    @classmethod
    def from_env(cls) -> "LabSettings":
        return cls(
            mode=os.getenv("YURA_INTERNAL_DIRECTIVE_LAB_MODE", "fake").strip().lower(),
            model=os.getenv("YURA_INTERNAL_DIRECTIVE_LAB_MODEL", "").strip(),
            api_key_env=os.getenv(
                "YURA_INTERNAL_DIRECTIVE_LAB_API_KEY_ENV",
                "OPENAI_API_KEY",
            ).strip(),
            timeout_seconds=float(
                os.getenv("YURA_INTERNAL_DIRECTIVE_LAB_TIMEOUT_SECONDS", "45")
            ),
            username=os.getenv("YURA_LAB_USERNAME", "").strip(),
            password=os.getenv("YURA_LAB_PASSWORD", ""),
        )

    @property
    def auth_configured(self) -> bool:
        return bool(self.username and self.password)

    @property
    def live_configured(self) -> bool:
        return bool(
            self.mode == "live"
            and self.model
            and self.api_key_env
            and os.getenv(self.api_key_env)
        )


class InternalDirectiveRequest(BaseModel):
    structured_input_meaning: dict[str, object] = Field(
        default_factory=lambda: deepcopy(_DEFAULT_MEANING)
    )
    internal_state: dict[str, object] = Field(
        default_factory=lambda: deepcopy(_DEFAULT_INTERNAL_STATE)
    )
    ongoing_activity: dict[str, object] | None = None
    available_activities: list[dict[str, object]] = Field(
        default_factory=lambda: deepcopy(_DEFAULT_AVAILABLE_ACTIVITIES)
    )
    character_profile: dict[str, object] = Field(
        default_factory=lambda: deepcopy(_DEFAULT_CHARACTER_PROFILE)
    )
    include_prompt: bool = False


class InternalDirectiveModel(Protocol):
    async def plan_internal_directive(self, activity: Activity) -> str: ...


class _FakeInternalDirectiveModel:
    async def plan_internal_directive(self, activity: Activity) -> str:
        meaning = activity.context.get("structured_input_meaning")
        meaning_data = meaning if isinstance(meaning, dict) else {}
        expected_response = str(meaning_data.get("expected_response") or "")
        speech_act = str(meaning_data.get("input_speech_act") or "")
        if expected_response == "direct_answer" or speech_act == "question":
            response_mode = "answer"
            response_goal = "質問へ直接答える"
        elif speech_act == "closing":
            response_mode = "react"
            response_goal = "短く会話を締める"
        elif speech_act == "acknowledgement":
            response_mode = "listen"
            response_goal = "新しい話題を始めず受け止める"
        else:
            response_mode = "react"
            response_goal = "入力内容へ簡潔に反応する"
        return json.dumps(
            {
                "response_mode": response_mode,
                "response_goal": response_goal,
                "activity_intent": None,
                "initiative_level": 0.2,
                "question_budget": 0,
                "new_direction_budget": 0,
                "self_disclosure_level": 0.2,
                "content_requirements": ["StructuredInputMeaningを主入力として扱う"],
                "forbidden_claims": ["根拠のない身体経験を語らない"],
                "target_interest_updates": [],
                "state_update_proposals": [],
                "reason": "Fake mode deterministic response",
            },
            ensure_ascii=False,
        )


class _UnavailableInternalDirectiveModel:
    def __init__(self, reason: str) -> None:
        self._reason = reason

    async def plan_internal_directive(self, activity: Activity) -> str:
        del activity
        raise RuntimeError(self._reason)


class _RecordingInternalDirectiveModel:
    def __init__(self, delegate: InternalDirectiveModel) -> None:
        self._delegate = delegate
        self.raw_response: str | None = None
        self.error: Exception | None = None

    def reset(self) -> None:
        self.raw_response = None
        self.error = None

    async def plan_internal_directive(self, activity: Activity) -> str:
        try:
            raw = await self._delegate.plan_internal_directive(activity)
        except Exception as error:
            self.error = error
            raise
        self.raw_response = str(raw)
        return self.raw_response


class InternalDirectiveLabService:
    def __init__(
        self,
        settings: LabSettings,
        *,
        model: InternalDirectiveModel | None = None,
    ) -> None:
        self._settings = settings
        self._prompt_builder = InternalDirectivePromptBuilder()
        self._meaning_parser = InputMeaningJsonParser()
        delegate = model or self._build_model(settings)
        self._recording_model = _RecordingInternalDirectiveModel(delegate)
        self._planner = InternalDirectivePlanner(
            self._recording_model,
            prompt_builder=self._prompt_builder,
        )

    async def analyze(self, request: InternalDirectiveRequest) -> dict[str, object]:
        meaning = self._meaning_parser.parse(
            json.dumps(request.structured_input_meaning, ensure_ascii=False),
            source_text="",
        )
        if meaning is None:
            raise ValueError(
                "structured_input_meaningがStructuredInputMeaning契約を満たしていません"
            )

        source_event_id = f"directive-cloud-lab-{uuid4()}"
        planning_input = self._planning_input(request)
        character_profile = dict(request.character_profile)
        prompt = self._prompt_builder.build(
            meaning,
            planning_input,
            character_profile=character_profile,
        )
        activity = Activity(
            activity_type=ActivityType.BEHAVIOR_PLANNING,
            goal="クラウド検証環境でInternalDirective候補を生成する",
            context={
                "event_id": source_event_id,
                "trace_context": None,
                "cloud_validation": True,
            },
            source_event_id=source_event_id,
        )

        self._recording_model.reset()
        started = perf_counter()
        directive = await self._planner.plan(
            activity,
            meaning,
            planning_input,
            character_profile=character_profile,
        )
        elapsed_ms = round((perf_counter() - started) * 1000.0, 3)
        raw_response = self._recording_model.raw_response
        model_error = self._recording_model.error

        error_type: str | None = None
        error_message: str | None = None
        if model_error is not None:
            error_type = type(model_error).__name__
            error_message = str(model_error)
        elif raw_response == _FALLBACK_RESPONSE:
            error_type = "provider_unavailable"
            error_message = "LLM Providerへの接続または応答取得に失敗しました"
        elif directive is None:
            error_type = "schema_validation_failed"
            error_message = "InternalDirectiveJsonParserが応答を受理しませんでした"

        result: dict[str, object] = {
            "source_event_id": source_event_id,
            "mode": self._settings.mode,
            "provider": "fake" if self._settings.mode == "fake" else "openai",
            "model": self._settings.model or None,
            "valid": directive is not None,
            "elapsed_ms": elapsed_ms,
            "structured_input_meaning": meaning.as_context(),
            "raw_response": raw_response,
            "parsed_response": (
                directive.as_context() if directive is not None else None
            ),
            "error_type": error_type,
            "error_message": error_message,
            "stopped_at": "internal_directive_planner",
            "executed_later_stages": [],
            "not_executed": [
                "internal_directive_validator",
                "activity_execution",
                "character_model",
                "response_validator",
                "output_plugins",
            ],
        }
        if request.include_prompt:
            result["prompt"] = prompt
        return result

    @staticmethod
    def _planning_input(request: InternalDirectiveRequest) -> dict[str, object]:
        state = dict(request.internal_state)
        return {
            "emotion": state.get("emotion", {}),
            "drive": state.get("drive", {}),
            "relationship": state.get("relationship", {}),
            "motivation": state.get("motivation", {}),
            "moral": state.get("moral", {}),
            "situation": state.get("situation", {}),
            "memory": state.get("memory", {}),
            "related_knowledge": state.get("related_knowledge", []),
            "last_activity_result": state.get("last_activity_result"),
            "ongoing_activity": request.ongoing_activity,
            "available_activities": [
                dict(activity) for activity in request.available_activities
            ],
        }

    @staticmethod
    def _build_model(settings: LabSettings) -> InternalDirectiveModel:
        if settings.mode == "fake":
            return _FakeInternalDirectiveModel()
        if settings.mode != "live":
            return _UnavailableInternalDirectiveModel(
                "YURA_INTERNAL_DIRECTIVE_LAB_MODEはfakeまたはliveを指定してください"
            )
        if not settings.model:
            return _UnavailableInternalDirectiveModel(
                "YURA_INTERNAL_DIRECTIVE_LAB_MODELが未設定です"
            )
        if not os.getenv(settings.api_key_env):
            return _UnavailableInternalDirectiveModel(
                f"{settings.api_key_env}が未設定です"
            )

        profile = CharacterProfile(
            name="ゆら",
            personality="司令塔LLMクラウド検証用の最小構成",
            speaking_style="日本語",
            streaming_style="Internal Directive生成のみ",
        )
        generator = OpenAIResponseGenerator(
            model=settings.model,
            api_key_env=settings.api_key_env,
            timeout_seconds=settings.timeout_seconds,
            fallback_response=_FALLBACK_RESPONSE,
            character_profile=profile,
            prompt_builder=SimplePromptBuilder(),
        )
        return ResponseGeneratorRoleAdapter(generator)


_security = HTTPBasic(auto_error=False)


def create_app(
    *,
    settings: LabSettings | None = None,
    service: InternalDirectiveLabService | None = None,
) -> FastAPI:
    resolved_settings = settings or LabSettings.from_env()
    resolved_service = service or InternalDirectiveLabService(resolved_settings)
    application = FastAPI(
        title="Yura Internal Directive Lab",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    def require_auth(
        credentials: HTTPBasicCredentials | None = Depends(_security),
    ) -> str:
        if not resolved_settings.auth_configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="検証画面の認証情報が未設定です",
            )
        valid = bool(
            credentials
            and secrets.compare_digest(
                credentials.username.encode("utf-8"),
                resolved_settings.username.encode("utf-8"),
            )
            and secrets.compare_digest(
                credentials.password.encode("utf-8"),
                resolved_settings.password.encode("utf-8"),
            )
        )
        if not valid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="認証に失敗しました",
                headers={"WWW-Authenticate": "Basic"},
            )
        return resolved_settings.username

    @application.get("/health")
    async def health() -> dict[str, object]:
        return {
            "status": "ok",
            "mode": resolved_settings.mode,
            "auth_configured": resolved_settings.auth_configured,
            "live_configured": resolved_settings.live_configured,
            "model_configured": bool(resolved_settings.model),
            "stop_stage": "internal_directive_planner",
        }

    @application.get("/", response_class=HTMLResponse)
    async def index(_: str = Depends(require_auth)) -> HTMLResponse:
        return HTMLResponse(_INDEX_HTML)

    @application.post("/api/internal-directive")
    async def analyze(
        request: InternalDirectiveRequest,
        _: str = Depends(require_auth),
    ) -> dict[str, object]:
        try:
            return await resolved_service.analyze(request)
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(error),
            ) from error

    return application


app = create_app()


_INDEX_HTML_TEMPLATE = (
    Path(__file__).with_name("internal_directive_lab.html").read_text(encoding="utf-8")
)
_INDEX_HTML = (
    _INDEX_HTML_TEMPLATE.replace(
        "__DEFAULT_MEANING__", json.dumps(_DEFAULT_MEANING, ensure_ascii=False)
    )
    .replace(
        "__DEFAULT_INTERNAL_STATE__",
        json.dumps(_DEFAULT_INTERNAL_STATE, ensure_ascii=False),
    )
    .replace(
        "__DEFAULT_AVAILABLE_ACTIVITIES__",
        json.dumps(_DEFAULT_AVAILABLE_ACTIVITIES, ensure_ascii=False),
    )
    .replace(
        "__DEFAULT_CHARACTER_PROFILE__",
        json.dumps(_DEFAULT_CHARACTER_PROFILE, ensure_ascii=False),
    )
)
