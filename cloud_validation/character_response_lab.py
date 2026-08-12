from __future__ import annotations

import json
import os
import secrets
from copy import deepcopy
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from enum import Enum
from time import perf_counter
from typing import Protocol
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field

from app.adapters.llm import OpenAIResponseGenerator
from app.adapters.prompt import (
    CharacterPromptBuilder,
    ResponseValidatorPromptBuilder,
    SimplePromptBuilder,
)
from app.domain.activities import Activity, ActivityType
from app.domain.character import CharacterExistenceProfile, CharacterProfile
from app.domain.character_response import (
    ActivityExecutionResult,
    ActivityExecutionStatus,
    ResponseClaim,
)
from app.domain.cognitive_direction import (
    ActivityIntent,
    ConversationPhaseSignal,
    ExpectedResponse,
    InputSpeechAct,
    InputTarget,
    InternalDirective,
    ResponseMode,
    StructuredInputMeaning,
    ValidatedActionPlan,
)
from app.ports.llm_roles import ResponseGeneratorRoleAdapter
from app.runtime.character_response_pipeline import (
    CharacterLlmService,
    CharacterResponsePipeline,
    ResponseContextBuilder,
    ResponseValidator,
)

_FALLBACK_RESPONSE = "__YURA_CHARACTER_RESPONSE_LAB_PROVIDER_UNAVAILABLE__"

_DEFAULT_CHARACTER_PROFILE: dict[str, object] = {
    "name": "ゆら",
    "personality": "穏やかで好奇心を持つが、相手の意図を優先する",
    "speaking_style": "自然な日本語。内部状態を診断レポートのように説明しない",
    "streaming_style": "会話相手へ自然に反応する",
    "likes": [],
    "dislikes": [],
    "behavior_policy": [],
}

_DEFAULT_MEANING: dict[str, object] = {
    "input_speech_act": "question",
    "primary_intent": "ask_internal_state",
    "expected_response": "direct_answer",
    "target": {"type": "internal_state", "id": "joy"},
    "conversation_phase_signal": "continue",
    "confidence": 0.99,
    "reason": "ユーザーは現在の楽しさを直接尋ねている",
}

_DEFAULT_DIRECTIVE: dict[str, object] = {
    "response_mode": "answer",
    "response_goal": "ユーザーが尋ねた内的状態について、現在の状態に沿って自然に直接答える",
    "activity_intent": None,
    "initiative_level": 0.2,
    "question_budget": 0,
    "new_direction_budget": 0,
    "self_disclosure_level": 0.35,
    "content_requirements": [],
    "forbidden_claims": [
        "engagementやcuriosityを、質問対象の内的状態と同一概念として扱う"
    ],
    "reason": "内部状態への直接質問へ必要十分に答える",
}

_DEFAULT_EMOTION: dict[str, object] = {
    "current": {
        "reactive": {
            "joy": 0.0,
            "amusement": 0.0,
            "calm": 0.58,
            "anger": 0.0,
        }
    }
}

_DEFAULT_DRIVE: dict[str, float] = {
    "curiosity": 0.61,
    "engagement": 0.57,
    "energy": 0.7,
}


def _preset(
    *,
    label: str,
    user_input: str,
    target_id: str,
    emotion: dict[str, object],
    drive: dict[str, float],
    recent_speech_summary: str = "",
) -> dict[str, object]:
    meaning = deepcopy(_DEFAULT_MEANING)
    meaning["target"] = {"type": "internal_state", "id": target_id}
    return {
        "label": label,
        "data": {
            "user_input": user_input,
            "structured_input_meaning": meaning,
            "internal_directive": deepcopy(_DEFAULT_DIRECTIVE),
            "emotion": deepcopy(emotion),
            "drive": deepcopy(drive),
            "memory": {},
            "related_knowledge": [],
            "recent_speech_summary": recent_speech_summary,
            "recent_conversation": [],
            "recent_topic_summary": "",
            "response_constraints": {"avoid_repetition": True},
            "character_profile": deepcopy(_DEFAULT_CHARACTER_PROFILE),
            "include_prompts": False,
        },
    }


_PRESETS: dict[str, dict[str, object]] = {
    "joy_low_curiosity_high": _preset(
        label="低いJoy / 高いCuriosity",
        user_input="楽しい？",
        target_id="joy",
        emotion=deepcopy(_DEFAULT_EMOTION),
        drive={"curiosity": 0.82, "engagement": 0.78, "energy": 0.7},
    ),
    "current_feeling_repeat": _preset(
        label="現在の気分・反復",
        user_input="今どんな気分？",
        target_id="current_feeling",
        emotion={
            "current": {
                "reactive": {
                    "joy": 0.18,
                    "amusement": 0.08,
                    "calm": 0.64,
                    "anger": 0.0,
                }
            }
        },
        drive={"curiosity": 0.52, "engagement": 0.58, "energy": 0.7},
        recent_speech_summary="- 今は落ち着いてて、ちょっとだけ元気がある感じかな。",
    ),
    "anger_low": _preset(
        label="低いAnger",
        user_input="怒ってる？",
        target_id="anger",
        emotion={
            "current": {
                "reactive": {
                    "joy": 0.12,
                    "amusement": 0.05,
                    "calm": 0.62,
                    "anger": 0.0,
                }
            }
        },
        drive={"curiosity": 0.48, "engagement": 0.55, "energy": 0.68},
    ),
    "current_desire": _preset(
        label="現在の欲求",
        user_input="何かしたい？",
        target_id="current_desire",
        emotion={
            "current": {
                "reactive": {
                    "joy": 0.14,
                    "amusement": 0.08,
                    "calm": 0.6,
                    "anger": 0.0,
                }
            }
        },
        drive={"curiosity": 0.55, "engagement": 0.51, "energy": 0.66},
    ),
}


@dataclass(frozen=True, slots=True)
class LabSettings:
    mode: str
    model: str
    validator_model: str
    api_key_env: str
    timeout_seconds: float
    username: str
    password: str

    @classmethod
    def from_env(cls) -> "LabSettings":
        model = os.getenv("YURA_CHARACTER_RESPONSE_LAB_MODEL", "").strip()
        return cls(
            mode=os.getenv("YURA_CHARACTER_RESPONSE_LAB_MODE", "fake").strip().lower(),
            model=model,
            validator_model=os.getenv(
                "YURA_CHARACTER_RESPONSE_LAB_VALIDATOR_MODEL", model
            ).strip(),
            api_key_env=os.getenv(
                "YURA_CHARACTER_RESPONSE_LAB_API_KEY_ENV", "OPENAI_API_KEY"
            ).strip(),
            timeout_seconds=float(
                os.getenv("YURA_CHARACTER_RESPONSE_LAB_TIMEOUT_SECONDS", "60")
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
            and self.validator_model
            and self.api_key_env
            and os.getenv(self.api_key_env)
        )


class CharacterResponseLabRequest(BaseModel):
    user_input: str = "楽しい？"
    structured_input_meaning: dict[str, object] = Field(
        default_factory=lambda: deepcopy(_DEFAULT_MEANING)
    )
    internal_directive: dict[str, object] = Field(
        default_factory=lambda: deepcopy(_DEFAULT_DIRECTIVE)
    )
    emotion: dict[str, object] = Field(
        default_factory=lambda: deepcopy(_DEFAULT_EMOTION)
    )
    drive: dict[str, float] = Field(default_factory=lambda: deepcopy(_DEFAULT_DRIVE))
    memory: dict[str, object] = Field(default_factory=dict)
    related_knowledge: list[object] = Field(default_factory=list)
    recent_speech_summary: str = ""
    recent_conversation: list[dict[str, object]] = Field(default_factory=list)
    recent_topic_summary: str = ""
    response_constraints: dict[str, object] = Field(
        default_factory=lambda: {"avoid_repetition": True}
    )
    character_profile: dict[str, object] = Field(
        default_factory=lambda: deepcopy(_DEFAULT_CHARACTER_PROFILE)
    )
    include_prompts: bool = False


class _CharacterRoleModel(Protocol):
    async def generate_character_response(self, activity: Activity) -> str: ...


class _ValidatorRoleModel(Protocol):
    async def validate_character_response(self, activity: Activity) -> str: ...


class _FakeRoleModel:
    async def generate_character_response(self, activity: Activity) -> str:
        del activity
        return json.dumps(
            {
                "speech": "検証用の応答です。",
                "expression": "soft_smile",
                "gesture": None,
                "voice_intent": {
                    "style": "gentle",
                    "speed": 1.0,
                    "pitch": 0.0,
                    "intonation": 1.0,
                    "volume": 1.0,
                    "breathiness": 0.0,
                    "emotional_leakage": 0.0,
                },
                "pause_after_seconds": 0.0,
                "reaction_segments": None,
                "claims": [
                    {
                        "claim_type": "conversation_only",
                        "activity_type": None,
                        "operation": None,
                        "status": None,
                        "target": None,
                        "confidence": 1.0,
                        "evidence": "fake mode wiring validation",
                    }
                ],
            },
            ensure_ascii=False,
        )

    async def validate_character_response(self, activity: Activity) -> str:
        del activity
        return json.dumps(
            {
                "accepted": True,
                "reason": "facts_consistent",
                "extracted_claims": [
                    {
                        "claim_type": "conversation_only",
                        "activity_type": None,
                        "operation": None,
                        "status": None,
                        "target": None,
                        "confidence": 1.0,
                        "evidence": "fake mode wiring validation",
                    }
                ],
            },
            ensure_ascii=False,
        )


class _UnavailableRoleModel:
    def __init__(self, reason: str) -> None:
        self._reason = reason

    async def generate_character_response(self, activity: Activity) -> str:
        del activity
        raise RuntimeError(self._reason)

    async def validate_character_response(self, activity: Activity) -> str:
        del activity
        raise RuntimeError(self._reason)


class _RecordingCharacterModel:
    def __init__(self, delegate: _CharacterRoleModel, records: list[dict[str, object]]) -> None:
        self._delegate = delegate
        self._records = records

    async def generate_character_response(self, activity: Activity) -> str:
        raw = await self._delegate.generate_character_response(activity)
        self._records.append(_record_call("character", activity, raw))
        return raw


class _RecordingValidatorModel:
    def __init__(self, delegate: _ValidatorRoleModel, records: list[dict[str, object]]) -> None:
        self._delegate = delegate
        self._records = records

    async def validate_character_response(self, activity: Activity) -> str:
        raw = await self._delegate.validate_character_response(activity)
        self._records.append(_record_call("validator", activity, raw))
        return raw


def _record_call(role: str, activity: Activity, raw: str) -> dict[str, object]:
    prompt = activity.context.get("plugin_prompt_override")
    return {
        "role": role,
        "raw_response": raw,
        "parsed_response": _parse_json_object(raw),
        "prompt": str(prompt) if isinstance(prompt, str) else None,
    }


def _parse_json_object(raw: str) -> dict[str, object] | None:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            text = "\n".join(lines[1:-1]).strip()
            if text.startswith("json"):
                text = text[4:].strip()
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    return dict(payload) if isinstance(payload, dict) else None


def _jsonable(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


class CharacterResponseLabService:
    def __init__(
        self,
        settings: LabSettings,
        *,
        character_model: _CharacterRoleModel | None = None,
        validator_model: _ValidatorRoleModel | None = None,
    ) -> None:
        self._settings = settings
        self._injected_character_model = character_model
        self._injected_validator_model = validator_model

    async def analyze(self, request: CharacterResponseLabRequest) -> dict[str, object]:
        profile = self._character_profile(request.character_profile)
        meaning = self._meaning(request.structured_input_meaning)
        directive = self._directive(request.internal_directive)
        envelope = ValidatedActionPlan(
            meaning=meaning,
            directive=directive,
            character_profile=dict(request.character_profile),
            existence_boundaries=profile.existence.behavior_policies(),
        ).as_context()
        source_event_id = f"character-response-lab-{uuid4()}"
        constraints = dict(request.response_constraints)
        constraints["_internal_directive"] = envelope
        result = ActivityExecutionResult(
            activity_type="conversation",
            operation="discuss",
            status=ActivityExecutionStatus.WAITING_INPUT,
            payload={"summary": "Character/Validator Labで会話応答を生成する"},
            constraints=constraints,
            source_event_id=source_event_id,
        )
        behavior_plan = {
            "speech_act": meaning.input_speech_act.value,
            "conversation_phase": self._conversation_phase(meaning),
            "initiative_level": directive.initiative_level,
        }
        activity = Activity(
            activity_type=ActivityType.CONVERSATION_WITH_USER,
            goal=directive.response_goal,
            context={
                "emotion": deepcopy(request.emotion),
                "event_payload": {
                    "text": request.user_input,
                    "activity_execution_result": result,
                    "behavior_plan": behavior_plan,
                    "autonomous_situation_context": {
                        "drive_state": dict(request.drive),
                        "recent_speech_summary": request.recent_speech_summary,
                        "recent_topic_summary": request.recent_topic_summary,
                    },
                    "memory": deepcopy(request.memory),
                    "related_knowledge": deepcopy(request.related_knowledge),
                    "conversation_history": deepcopy(request.recent_conversation),
                },
                "cloud_validation": True,
            },
            source_event_id=source_event_id,
        )

        records: list[dict[str, object]] = []
        character_delegate, validator_delegate = self._build_models(profile)
        character_model = _RecordingCharacterModel(character_delegate, records)
        validator_model = _RecordingValidatorModel(validator_delegate, records)
        pipeline = CharacterResponsePipeline(
            ResponseContextBuilder(),
            CharacterLlmService(
                character_model,
                CharacterPromptBuilder(),
                character_profile=profile,
            ),
            ResponseValidator(
                validator_model,
                ResponseValidatorPromptBuilder(),
            ),
        )

        started = perf_counter()
        response, generation_result = await pipeline.generate_with_result(activity)
        elapsed_ms = round((perf_counter() - started) * 1000.0, 3)

        if not request.include_prompts:
            for record in records:
                record.pop("prompt", None)

        context = ResponseContextBuilder().build(activity)
        return {
            "source_event_id": source_event_id,
            "mode": self._settings.mode,
            "provider": "fake" if self._settings.mode == "fake" else "openai",
            "model": self._settings.model or None,
            "validator_model": self._settings.validator_model or None,
            "elapsed_ms": elapsed_ms,
            "typed_target": meaning.target.as_context() if meaning.target else None,
            "structured_input_meaning": meaning.as_context(),
            "internal_directive": directive.as_context(),
            "response_context": _jsonable(context),
            "model_calls": records,
            "final_response": _jsonable(response),
            "generation_result": _jsonable(generation_result),
            "stopped_at": "character_response_pipeline",
            "not_executed": [
                "tts",
                "body_runtime",
                "avatar_output",
                "output_plugins",
                "full_runtime_coordinator",
            ],
        }

    @staticmethod
    def _conversation_phase(meaning: StructuredInputMeaning) -> str:
        signal = meaning.conversation_phase_signal
        if signal is ConversationPhaseSignal.WINDING_DOWN:
            return "winding_down"
        if signal in {ConversationPhaseSignal.GREETING, ConversationPhaseSignal.OPENING}:
            return "greeting"
        return "active"

    def _build_models(
        self,
        profile: CharacterProfile,
    ) -> tuple[_CharacterRoleModel, _ValidatorRoleModel]:
        if self._injected_character_model is not None:
            character_model = self._injected_character_model
        else:
            character_model = self._build_role_model(profile, self._settings.model)
        if self._injected_validator_model is not None:
            validator_model = self._injected_validator_model
        else:
            validator_model = self._build_role_model(
                profile,
                self._settings.validator_model,
            )
        return character_model, validator_model

    def _build_role_model(
        self,
        profile: CharacterProfile,
        model_name: str,
    ) -> ResponseGeneratorRoleAdapter | _FakeRoleModel | _UnavailableRoleModel:
        if self._settings.mode == "fake":
            return _FakeRoleModel()
        if self._settings.mode != "live":
            return _UnavailableRoleModel(
                "YURA_CHARACTER_RESPONSE_LAB_MODEはfakeまたはliveを指定してください"
            )
        if not model_name:
            return _UnavailableRoleModel("Character Response Labのmodelが未設定です")
        if not os.getenv(self._settings.api_key_env):
            return _UnavailableRoleModel(f"{self._settings.api_key_env}が未設定です")
        generator = OpenAIResponseGenerator(
            model=model_name,
            api_key_env=self._settings.api_key_env,
            timeout_seconds=self._settings.timeout_seconds,
            fallback_response=_FALLBACK_RESPONSE,
            character_profile=profile,
            prompt_builder=SimplePromptBuilder(),
        )
        return ResponseGeneratorRoleAdapter(generator)

    @staticmethod
    def _meaning(data: dict[str, object]) -> StructuredInputMeaning:
        target_value = data.get("target")
        target = None
        if isinstance(target_value, dict):
            target = InputTarget(
                str(target_value.get("type") or ""),
                str(target_value.get("id") or ""),
            )
        return StructuredInputMeaning(
            input_speech_act=InputSpeechAct(str(data.get("input_speech_act") or "question")),
            primary_intent=str(data.get("primary_intent") or "ask_internal_state"),
            expected_response=ExpectedResponse(
                str(data.get("expected_response") or "direct_answer")
            ),
            target=target,
            entities=tuple(
                dict(item)
                for item in data.get("entities", [])
                if isinstance(item, dict)
            ),
            references=tuple(
                dict(item)
                for item in data.get("references", [])
                if isinstance(item, dict)
            ),
            information_provided=tuple(
                str(item) for item in data.get("information_provided", [])
            ),
            negated=bool(data.get("negated", False)),
            hypothetical=bool(data.get("hypothetical", False)),
            past_reference=bool(data.get("past_reference", False)),
            conversation_phase_signal=ConversationPhaseSignal(
                str(data.get("conversation_phase_signal") or "continue")
            ),
            confidence=float(data.get("confidence", 1.0)),
            reason=str(data.get("reason") or ""),
        )

    @staticmethod
    def _directive(data: dict[str, object]) -> InternalDirective:
        activity_value = data.get("activity_intent")
        activity_intent = None
        if isinstance(activity_value, dict):
            activity_intent = ActivityIntent(
                activity_type=str(activity_value.get("activity_type") or "conversation"),
                operation=str(activity_value.get("operation") or "discuss"),
                constraints=(
                    dict(activity_value.get("constraints", {}))
                    if isinstance(activity_value.get("constraints"), dict)
                    else {}
                ),
            )
        return InternalDirective(
            response_mode=ResponseMode(str(data.get("response_mode") or "answer")),
            response_goal=str(data.get("response_goal") or "質問へ自然に答える"),
            activity_intent=activity_intent,
            initiative_level=float(data.get("initiative_level", 0.2)),
            question_budget=int(data.get("question_budget", 0)),
            new_direction_budget=int(data.get("new_direction_budget", 0)),
            self_disclosure_level=float(data.get("self_disclosure_level", 0.35)),
            content_requirements=tuple(
                str(item) for item in data.get("content_requirements", [])
            ),
            forbidden_claims=tuple(
                str(item) for item in data.get("forbidden_claims", [])
            ),
            reason=str(data.get("reason") or ""),
        )

    @staticmethod
    def _character_profile(data: dict[str, object]) -> CharacterProfile:
        existence_value = data.get("existence")
        existence_data = existence_value if isinstance(existence_value, dict) else {}
        existence = CharacterExistenceProfile(
            existence_type=str(existence_data.get("existence_type") or "AI VTuber"),
            home_environment=str(
                existence_data.get("home_environment") or "コンピューター上の仮想空間"
            ),
            physical_capabilities=tuple(
                str(item)
                for item in existence_data.get(
                    "physical_capabilities", ["物理的な身体を持たない"]
                )
            ),
            sensory_capabilities=tuple(
                str(item)
                for item in existence_data.get(
                    "sensory_capabilities",
                    ["接続された入力や提供された情報から外界を認識する"],
                )
            ),
            experience_boundaries=tuple(
                str(item)
                for item in existence_data.get(
                    "experience_boundaries",
                    ["見た・行った・触った等の実体験は根拠がある場合だけ語る"],
                )
            ),
            world_relationship=str(
                existence_data.get("world_relationship")
                or "海をモチーフとして好むが、海中に居住している設定ではない"
            ),
        )
        return CharacterProfile(
            name=str(data.get("name") or "ゆら"),
            personality=str(data.get("personality") or "穏やか"),
            speaking_style=str(data.get("speaking_style") or "自然な日本語"),
            streaming_style=str(data.get("streaming_style") or "自然な会話"),
            likes=[str(item) for item in data.get("likes", [])],
            dislikes=[str(item) for item in data.get("dislikes", [])],
            behavior_policy=[str(item) for item in data.get("behavior_policy", [])],
            existence=existence,
        )


_security = HTTPBasic(auto_error=False)


def create_app(
    *,
    settings: LabSettings | None = None,
    service: CharacterResponseLabService | None = None,
) -> FastAPI:
    resolved_settings = settings or LabSettings.from_env()
    resolved_service = service or CharacterResponseLabService(resolved_settings)
    application = FastAPI(
        title="Yura Character / Response Validator Lab",
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
            "validator_model_configured": bool(resolved_settings.validator_model),
            "stop_stage": "character_response_pipeline",
        }

    @application.get("/api/presets")
    async def presets(_: str = Depends(require_auth)) -> dict[str, object]:
        return deepcopy(_PRESETS)

    @application.get("/", response_class=HTMLResponse)
    async def index(_: str = Depends(require_auth)) -> HTMLResponse:
        return HTMLResponse(_INDEX_HTML)

    @application.post("/api/character-response")
    async def analyze(
        request: CharacterResponseLabRequest,
        _: str = Depends(require_auth),
    ) -> dict[str, object]:
        try:
            return await resolved_service.analyze(request)
        except (TypeError, ValueError) as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(error),
            ) from error

    return application


app = create_app()


_INDEX_HTML = r"""
<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Yura Character / Validator Lab</title>
<style>
:root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, -apple-system, sans-serif; }
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; background: radial-gradient(circle at 50% -20%, #164267 0, #071521 38%, #03090f 75%); color: #e8f5ff; }
main { width: min(1440px, 96vw); margin: 0 auto; padding: 28px 0 54px; }
header { display:flex; gap:18px; justify-content:space-between; align-items:flex-end; margin-bottom:18px; }
h1 { margin:0; font-size: clamp(24px, 3vw, 40px); letter-spacing:.02em; }
.subtitle { color:#9dc6df; margin-top:6px; }
.badge { border:1px solid #37637d; border-radius:999px; padding:7px 11px; color:#a9d8ef; background:#071b29cc; }
.toolbar, .card { border:1px solid #24485e; background:#071722d9; backdrop-filter: blur(12px); border-radius:16px; box-shadow:0 18px 42px #0006; }
.toolbar { display:grid; grid-template-columns: 1fr auto auto; gap:10px; padding:13px; margin-bottom:14px; }
select, button, input, textarea { font:inherit; }
select, input, textarea { width:100%; border:1px solid #31546a; color:#eaf7ff; background:#04111a; border-radius:10px; padding:10px 12px; }
button { border:1px solid #447089; color:#effaff; background:#0e3349; border-radius:10px; padding:10px 15px; cursor:pointer; font-weight:650; }
button:hover { background:#16445e; }
button.primary { background:#135274; border-color:#5ca4c8; }
.grid { display:grid; grid-template-columns: minmax(0, .95fr) minmax(0, 1.05fr); gap:14px; align-items:start; }
.card { padding:16px; }
.card h2 { margin:0 0 12px; font-size:17px; }
label { display:block; color:#9fc4d9; margin:10px 0 6px; font-size:13px; }
textarea { min-height:160px; resize:vertical; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size:12px; line-height:1.45; }
textarea.tall { min-height:260px; }
.result { white-space:pre-wrap; overflow-wrap:anywhere; background:#030b11; border:1px solid #26495c; border-radius:12px; padding:13px; min-height:260px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size:12px; line-height:1.5; }
.summary { display:grid; grid-template-columns:repeat(3,1fr); gap:8px; margin-bottom:12px; }
.kpi { border:1px solid #25485b; border-radius:11px; padding:10px; background:#06131d; }
.kpi small { color:#7fa9bf; display:block; }
.kpi strong { display:block; margin-top:4px; font-size:14px; }
details { border-top:1px solid #1b3d50; margin-top:12px; padding-top:9px; }
summary { cursor:pointer; color:#bde3f6; }
.status { margin:10px 0 0; color:#8fc7e3; min-height:1.4em; }
@media(max-width:900px){ .grid{grid-template-columns:1fr}.toolbar{grid-template-columns:1fr 1fr}.toolbar select{grid-column:1/-1}.summary{grid-template-columns:1fr} }
</style>
</head>
<body><main>
<header><div><h1>Character / Validator Lab</h1><div class="subtitle">Character生成 → Response Validator → regeneration を全体Runtimeなしで確認</div></div><div class="badge">stop: character_response_pipeline</div></header>
<div class="toolbar">
<select id="preset"></select>
<button id="load">プリセット読込</button>
<button id="run" class="primary">実行</button>
</div>
<div class="grid">
<section class="card">
<h2>Input Snapshot</h2>
<label>ユーザー入力</label><input id="userInput">
<label>StructuredInputMeaning</label><textarea id="meaning"></textarea>
<label>Internal Directive</label><textarea id="directive"></textarea>
<details open><summary>Emotion / Drive</summary><label>Emotion</label><textarea id="emotion"></textarea><label>Drive</label><textarea id="drive"></textarea></details>
<details><summary>Recent / Memory</summary><label>Recent speech summary</label><textarea id="recentSpeech"></textarea><label>Recent conversation (JSON array)</label><textarea id="conversation"></textarea><label>Recent topic summary</label><textarea id="recentTopic"></textarea><label>Memory</label><textarea id="memory"></textarea><label>Related knowledge</label><textarea id="knowledge"></textarea></details>
<details><summary>Constraints / Character</summary><label>Response constraints</label><textarea id="constraints"></textarea><label>Character Profile</label><textarea id="profile" class="tall"></textarea><label><input id="includePrompts" type="checkbox" style="width:auto"> Promptも結果に含める</label></details>
<div class="status" id="status"></div>
</section>
<section class="card">
<h2>Pipeline Result</h2>
<div class="summary"><div class="kpi"><small>Status</small><strong id="resultStatus">-</strong></div><div class="kpi"><small>Attempts</small><strong id="attempts">-</strong></div><div class="kpi"><small>Elapsed</small><strong id="elapsed">-</strong></div></div>
<button id="copy">結果JSONをコピー</button>
<div class="result" id="result">未実行</div>
</section>
</div>
</main>
<script>
let presets = {}; let lastResult = null;
const $ = id => document.getElementById(id);
const pretty = value => JSON.stringify(value, null, 2);
const parse = (id, fallback) => { const text=$(id).value.trim(); return text ? JSON.parse(text) : fallback; };
function apply(data){
 $('userInput').value=data.user_input||'';
 $('meaning').value=pretty(data.structured_input_meaning||{});
 $('directive').value=pretty(data.internal_directive||{});
 $('emotion').value=pretty(data.emotion||{});
 $('drive').value=pretty(data.drive||{});
 $('recentSpeech').value=data.recent_speech_summary||'';
 $('conversation').value=pretty(data.recent_conversation||[]);
 $('recentTopic').value=data.recent_topic_summary||'';
 $('memory').value=pretty(data.memory||{});
 $('knowledge').value=pretty(data.related_knowledge||[]);
 $('constraints').value=pretty(data.response_constraints||{});
 $('profile').value=pretty(data.character_profile||{});
 $('includePrompts').checked=!!data.include_prompts;
}
function requestData(){ return {
 user_input:$('userInput').value,
 structured_input_meaning:parse('meaning',{}), internal_directive:parse('directive',{}),
 emotion:parse('emotion',{}), drive:parse('drive',{}), memory:parse('memory',{}),
 related_knowledge:parse('knowledge',[]), recent_speech_summary:$('recentSpeech').value,
 recent_conversation:parse('conversation',[]), recent_topic_summary:$('recentTopic').value,
 response_constraints:parse('constraints',{}), character_profile:parse('profile',{}),
 include_prompts:$('includePrompts').checked
}; }
async function loadPresets(){
 const r=await fetch('/api/presets'); presets=await r.json();
 $('preset').innerHTML=Object.entries(presets).map(([key,v])=>`<option value="${key}">${v.label}</option>`).join('');
 const first=Object.keys(presets)[0]; if(first) apply(presets[first].data);
}
$('load').onclick=()=>{ const p=presets[$('preset').value]; if(p) apply(p.data); };
$('run').onclick=async()=>{
 try{
  $('status').textContent='実行中…'; $('run').disabled=true;
  const r=await fetch('/api/character-response',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(requestData())});
  const payload=await r.json(); if(!r.ok) throw new Error(payload.detail||`HTTP ${r.status}`);
  lastResult=payload; $('result').textContent=pretty(payload);
  $('resultStatus').textContent=payload.generation_result?.status||'-';
  $('attempts').textContent=payload.generation_result?.attempts??'-';
  $('elapsed').textContent=`${payload.elapsed_ms} ms`; $('status').textContent='完了';
 }catch(e){ $('status').textContent=`失敗: ${e.message}`; $('result').textContent=String(e.stack||e); }
 finally{$('run').disabled=false;}
};
$('copy').onclick=async()=>{ if(lastResult){ await navigator.clipboard.writeText(pretty(lastResult)); $('status').textContent='結果JSONをコピーしました'; } };
loadPresets().catch(e=>$('status').textContent=`初期化失敗: ${e.message}`);
</script>
</body></html>
"""
