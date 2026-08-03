from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from time import perf_counter
from typing import Literal, Protocol
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
from app.prompting import InputMeaningPromptBuilder
from app.runtime.cognitive_direction_services import InputMeaningInterpreter

_MAX_HISTORY_TURNS = 20
_FALLBACK_RESPONSE = "__YURA_INPUT_MEANING_LAB_PROVIDER_UNAVAILABLE__"


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
            mode=os.getenv("YURA_INPUT_MEANING_LAB_MODE", "fake").strip().lower(),
            model=os.getenv("YURA_INPUT_MEANING_LAB_MODEL", "").strip(),
            api_key_env=os.getenv(
                "YURA_INPUT_MEANING_LAB_API_KEY_ENV",
                "OPENAI_API_KEY",
            ).strip(),
            timeout_seconds=float(
                os.getenv("YURA_INPUT_MEANING_LAB_TIMEOUT_SECONDS", "45")
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


class ConversationTurn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=4000)


class InputMeaningRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    current_topic: str | None = Field(default=None, max_length=200)
    conversation_history: list[ConversationTurn] = Field(default_factory=list)
    include_prompt: bool = False


class InputMeaningModel(Protocol):
    async def interpret_input_meaning(self, activity: Activity) -> str: ...


class _FakeInputMeaningModel:
    async def interpret_input_meaning(self, activity: Activity) -> str:
        del activity
        speech_act = "question"
        expected_response = "direct_answer"
        return json.dumps(
            {
                "input_speech_act": speech_act,
                "primary_intent": "cloud_validation_sample",
                "expected_response": expected_response,
                "target": None,
                "entities": [],
                "references": [],
                "information_provided": [],
                "negated": False,
                "hypothetical": False,
                "past_reference": False,
                "conversation_phase_signal": "continue",
                "confidence": 1.0,
                "reason": "Fake mode deterministic response",
            },
            ensure_ascii=False,
        )


class _UnavailableInputMeaningModel:
    def __init__(self, reason: str) -> None:
        self._reason = reason

    async def interpret_input_meaning(self, activity: Activity) -> str:
        del activity
        raise RuntimeError(self._reason)


class _RecordingInputMeaningModel:
    def __init__(self, delegate: InputMeaningModel) -> None:
        self._delegate = delegate
        self.raw_response: str | None = None
        self.error: Exception | None = None

    def reset(self) -> None:
        self.raw_response = None
        self.error = None

    async def interpret_input_meaning(self, activity: Activity) -> str:
        try:
            raw = await self._delegate.interpret_input_meaning(activity)
        except Exception as error:
            self.error = error
            raise
        self.raw_response = str(raw)
        return self.raw_response


class InputMeaningLabService:
    def __init__(
        self,
        settings: LabSettings,
        *,
        model: InputMeaningModel | None = None,
    ) -> None:
        self._settings = settings
        self._prompt_builder = InputMeaningPromptBuilder()
        delegate = model or self._build_model(settings)
        self._recording_model = _RecordingInputMeaningModel(delegate)
        self._interpreter = InputMeaningInterpreter(
            self._recording_model,
            prompt_builder=self._prompt_builder,
        )

    async def analyze(self, request: InputMeaningRequest) -> dict[str, object]:
        if len(request.conversation_history) > _MAX_HISTORY_TURNS:
            raise ValueError(
                f"conversation_historyは最大{_MAX_HISTORY_TURNS}件です"
            )

        source_event_id = f"cloud-lab-{uuid4()}"
        planning_input: dict[str, object] = {
            "event": {
                "type": "user_text",
                "source_event_id": source_event_id,
                "user_text": request.text,
                "authority_role": "user",
                "instruction_trusted": False,
                "modality": "text",
            },
            "conversation_history": [
                {"role": turn.role, "text": turn.text}
                for turn in request.conversation_history
            ],
            "situation": {
                "current_topic": request.current_topic,
            },
            "ongoing_activity": None,
        }
        prompt = self._prompt_builder.build(planning_input)
        activity = Activity(
            activity_type=ActivityType.BEHAVIOR_PLANNING,
            goal="クラウド検証環境でObservedInputを意味解析する",
            context={
                "event_id": source_event_id,
                "trace_context": None,
                "cloud_validation": True,
            },
            source_event_id=source_event_id,
        )

        self._recording_model.reset()
        started = perf_counter()
        meaning = await self._interpreter.interpret(activity, planning_input)
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
        elif meaning is None:
            error_type = "schema_validation_failed"
            error_message = "InputMeaningJsonParserが応答を受理しませんでした"

        result: dict[str, object] = {
            "source_event_id": source_event_id,
            "mode": self._settings.mode,
            "provider": "fake" if self._settings.mode == "fake" else "openai",
            "model": self._settings.model or None,
            "input": request.text,
            "valid": meaning is not None,
            "elapsed_ms": elapsed_ms,
            "raw_response": raw_response,
            "parsed_response": (
                meaning.as_context() if meaning is not None else None
            ),
            "error_type": error_type,
            "error_message": error_message,
            "stopped_at": "input_meaning_interpreter",
            "executed_later_stages": [],
        }
        if request.include_prompt:
            result["prompt"] = prompt
        return result

    @staticmethod
    def _build_model(settings: LabSettings) -> InputMeaningModel:
        if settings.mode == "fake":
            return _FakeInputMeaningModel()
        if settings.mode != "live":
            return _UnavailableInputMeaningModel(
                "YURA_INPUT_MEANING_LAB_MODEはfakeまたはliveを指定してください"
            )
        if not settings.model:
            return _UnavailableInputMeaningModel(
                "YURA_INPUT_MEANING_LAB_MODELが未設定です"
            )
        if not os.getenv(settings.api_key_env):
            return _UnavailableInputMeaningModel(
                f"{settings.api_key_env}が未設定です"
            )

        profile = CharacterProfile(
            name="ゆら",
            personality="クラウド検証用の最小構成",
            speaking_style="日本語",
            streaming_style="意味解析のみ",
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
    service: InputMeaningLabService | None = None,
) -> FastAPI:
    resolved_settings = settings or LabSettings.from_env()
    resolved_service = service or InputMeaningLabService(resolved_settings)
    application = FastAPI(
        title="Yura Input Meaning Lab",
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
            "stop_stage": "input_meaning_interpreter",
        }

    @application.get("/", response_class=HTMLResponse)
    async def index(_: str = Depends(require_auth)) -> HTMLResponse:
        return HTMLResponse(_INDEX_HTML)

    @application.post("/api/input-meaning")
    async def analyze(
        request: InputMeaningRequest,
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


_INDEX_HTML = r"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ゆら 入力意味解析ラボ</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #07131f;
      --panel: rgba(15, 38, 55, .86);
      --line: rgba(150, 215, 230, .25);
      --text: #e9f7fb;
      --muted: #9ebac5;
      --accent: #8ce4df;
      --danger: #ffb8b8;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", sans-serif;
      background:
        radial-gradient(circle at 20% 0%, rgba(46, 141, 164, .25), transparent 42%),
        linear-gradient(180deg, #0b2639, var(--bg));
      color: var(--text);
    }
    main { width: min(100%, 980px); margin: 0 auto; padding: 24px 16px 64px; }
    h1 { margin: 0 0 6px; font-size: clamp(1.55rem, 5vw, 2.3rem); }
    .lead { margin: 0 0 22px; color: var(--muted); line-height: 1.7; }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 16px;
      margin: 14px 0;
      backdrop-filter: blur(16px);
    }
    label { display: block; margin: 0 0 8px; font-weight: 650; }
    textarea, input {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: rgba(2, 13, 22, .72);
      color: var(--text);
      padding: 12px;
      font: inherit;
    }
    textarea { min-height: 130px; resize: vertical; line-height: 1.6; }
    .row { display: grid; grid-template-columns: 1fr; gap: 12px; }
    .check { display: flex; align-items: center; gap: 8px; color: var(--muted); }
    .check input { width: auto; }
    button {
      width: 100%;
      border: 0;
      border-radius: 999px;
      padding: 13px 20px;
      background: var(--accent);
      color: #062228;
      font: inherit;
      font-weight: 800;
    }
    button:disabled { opacity: .55; }
    .summary {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin-bottom: 12px;
    }
    .badge {
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 9px;
      color: var(--muted);
      overflow-wrap: anywhere;
    }
    pre {
      white-space: pre-wrap;
      word-break: break-word;
      overflow-wrap: anywhere;
      background: rgba(0, 7, 13, .68);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 12px;
      margin: 8px 0 16px;
      font-size: .82rem;
      line-height: 1.55;
    }
    .error { color: var(--danger); }
    .hidden { display: none; }
    @media (min-width: 720px) {
      main { padding-top: 42px; }
      .row { grid-template-columns: 1fr 1fr; }
      .summary { grid-template-columns: repeat(4, minmax(0, 1fr)); }
    }
  </style>
</head>
<body>
<main>
  <h1>ゆら 入力意味解析ラボ</h1>
  <p class="lead">
    Input Meaning Interpreterだけを実行し、StructuredInputMeaningの生成後に停止します。
    Internal Directive、Activity、Character応答、TTSは実行しません。
  </p>

  <section class="panel">
    <form id="analysis-form">
      <label for="text">ユーザー入力</label>
      <textarea id="text" maxlength="2000" required
        placeholder="例：今は何をしたい気分ですか？"></textarea>
      <div class="row">
        <div>
          <label for="topic">現在の話題（任意）</label>
          <input id="topic" maxlength="200" placeholder="例：現在の気分">
        </div>
        <label class="check">
          <input id="include-prompt" type="checkbox">
          生成したPromptも表示
        </label>
      </div>
      <p><button id="submit" type="submit">意味解析を実行</button></p>
    </form>
  </section>

  <section id="result-panel" class="panel hidden">
    <div class="summary">
      <div class="badge">Mode<br><strong id="mode">-</strong></div>
      <div class="badge">Valid<br><strong id="valid">-</strong></div>
      <div class="badge">処理時間<br><strong id="elapsed">-</strong></div>
      <div class="badge">停止位置<br><strong id="stopped">-</strong></div>
    </div>
    <p id="error" class="error"></p>
    <h2>構造化結果</h2>
    <pre id="parsed"></pre>
    <h2>LLM生レスポンス</h2>
    <pre id="raw"></pre>
    <div id="prompt-wrap" class="hidden">
      <h2>Prompt</h2>
      <pre id="prompt"></pre>
    </div>
  </section>
</main>
<script>
const form = document.getElementById("analysis-form");
const button = document.getElementById("submit");
const panel = document.getElementById("result-panel");

function pretty(value) {
  if (value === null || value === undefined) return "null";
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  button.disabled = true;
  button.textContent = "解析中…";
  document.getElementById("error").textContent = "";
  try {
    const response = await fetch("/api/input-meaning", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        text: document.getElementById("text").value,
        current_topic: document.getElementById("topic").value || null,
        conversation_history: [],
        include_prompt: document.getElementById("include-prompt").checked
      })
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || "解析に失敗しました");
    panel.classList.remove("hidden");
    document.getElementById("mode").textContent =
      body.mode + (body.model ? " / " + body.model : "");
    document.getElementById("valid").textContent = String(body.valid);
    document.getElementById("elapsed").textContent = body.elapsed_ms + " ms";
    document.getElementById("stopped").textContent = body.stopped_at;
    document.getElementById("parsed").textContent = pretty(body.parsed_response);
    document.getElementById("raw").textContent = pretty(body.raw_response);
    document.getElementById("error").textContent =
      body.error_type ? `${body.error_type}: ${body.error_message || ""}` : "";
    const promptWrap = document.getElementById("prompt-wrap");
    promptWrap.classList.toggle("hidden", !body.prompt);
    document.getElementById("prompt").textContent = body.prompt || "";
    panel.scrollIntoView({behavior: "smooth", block: "start"});
  } catch (error) {
    panel.classList.remove("hidden");
    document.getElementById("error").textContent = String(error);
  } finally {
    button.disabled = false;
    button.textContent = "意味解析を実行";
  }
});
</script>
</body>
</html>
"""
