from __future__ import annotations

import argparse
import json
import mimetypes
import os
import threading
from copy import deepcopy
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

WEB_ROOT = Path(__file__).parent / "web"
DATA_ROOT = Path(os.getenv("YURA_CONFIG_CONSOLE_DATA", Path(__file__).parent / "data"))
STATE_PATH = DATA_ROOT / "state.json"
MAX_JSON_BYTES = 256 * 1024

CATEGORY_DEFINITIONS: list[dict[str, Any]] = [
    {"id": "runtime", "label": "実行環境・ログ", "file": "runtime.yaml", "description": "アプリ動作、ログ、入力受付、確認待ちを管理します。"},
    {"id": "character", "label": "キャラクター", "file": "character.yaml", "description": "名前、呼称、話し方などの固定プロフィールを管理します。"},
    {"id": "speech", "label": "音声・VoiceVox", "file": "speech.yaml", "description": "音声合成、話者、辞書、音声プロファイルを管理します。"},
    {"id": "memory", "label": "記憶", "file": "memory.yaml", "description": "短期・長期記憶とトピック記憶を管理します。"},
    {"id": "services", "label": "外部サービス", "file": "services.yaml", "description": "VoiceVox、DB、外部APIなどの接続先を管理します。"},
    {"id": "models", "label": "モデル定義", "file": "models.yaml", "description": "利用可能なLLM・Embeddingモデルを管理します。"},
    {"id": "llm", "label": "LLMルーティング", "file": "llm.yaml", "description": "応答生成と役割別モデル割当を管理します。"},
    {"id": "emotion", "label": "感情評価", "file": "emotion.yaml", "description": "感情評価、閾値、フォールバックを管理します。"},
    {"id": "streaming", "label": "配信", "file": "streaming.yaml", "description": "OBS、YouTube、配信進行設定を管理します。"},
    {"id": "plugins", "label": "プラグイン", "file": "plugins.yaml", "description": "プラグインの有効化と固有設定を管理します。"},
]

DEFAULT_VALUES: dict[str, dict[str, Any]] = {
    "runtime": {"app_name": "ai-liver", "mode": "console", "trace_level": "INFO", "trace_format": "text", "timer_enabled": False, "confirmation_timeout_seconds": 30},
    "character": {"character_name": "ゆら", "first_person": "ボク", "user_call_name": "キミ", "casual_speech": True},
    "speech": {"enabled": True, "service": "services.voicevox", "speaker_id": 46, "dictionary_path": "config/pronunciation_dictionary.yaml", "player_type": "local"},
    "memory": {"agent_memory_enabled": True, "relationship_memory_enabled": True, "topic_memory_enabled": True, "recall_limit": 8, "database_service": "services.topic_memory_database"},
    "services": {"voicevox_url": "http://127.0.0.1:50021", "topic_database": "postgresql", "request_timeout_seconds": 30},
    "models": {"talk_model": "ollama/qwen", "brain_model": "ollama/qwen", "organizer_model": "openai/gpt", "embedding_model": "openai/text-embedding"},
    "llm": {"response_generator": "role_router", "talk_role": "models.talk_model", "brain_role": "models.brain_model", "organizer_role": "models.organizer_model", "topic_classifier_enabled": True},
    "emotion": {"enabled": True, "model": "models.organizer_model", "timeout_seconds": 3, "confidence_threshold": 0.55, "fallback": "rule_based"},
    "streaming": {"enabled": False, "obs_host": "127.0.0.1", "obs_port": 4455, "youtube_mode": "manual", "auto_start": False},
    "plugins": {"tts": True, "live2d": False, "youtube": False, "obs": False, "external_search": False},
}

FIELD_METADATA: dict[str, dict[str, dict[str, Any]]] = {
    "speech": {
        "enabled": {"label": "読み上げを有効にする", "type": "boolean", "reload_policy": "next_request"},
        "service": {"label": "VoiceVox サービス", "type": "reference", "reference": "services.voicevox", "reload_policy": "reconnect"},
        "speaker_id": {"label": "話者 ID", "type": "integer", "minimum": 0, "reload_policy": "next_request"},
        "dictionary_path": {"label": "発音辞書", "type": "path", "reload_policy": "restart"},
        "player_type": {"label": "再生方式", "type": "select", "options": ["local", "browser", "disabled"], "reload_policy": "restart"},
    },
    "runtime": {
        "app_name": {"label": "アプリケーション名", "type": "string", "reload_policy": "restart"},
        "mode": {"label": "動作モード", "type": "select", "options": ["console", "streaming_demo"], "reload_policy": "restart"},
        "trace_level": {"label": "ログレベル", "type": "select", "options": ["DEBUG", "INFO", "WARNING", "ERROR", "OFF"], "reload_policy": "immediate"},
        "trace_format": {"label": "ログ形式", "type": "select", "options": ["text", "jsonl"], "reload_policy": "restart"},
        "timer_enabled": {"label": "タイマー入力", "type": "boolean", "reload_policy": "restart"},
        "confirmation_timeout_seconds": {"label": "確認待ち時間（秒）", "type": "integer", "minimum": 1, "reload_policy": "next_request"},
    },
    "character": {
        "casual_speech": {"label": "くだけた話し方", "type": "boolean", "reload_policy": "restart"},
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def initial_state() -> dict[str, Any]:
    return {"revision": 1, "updated_at": utc_now(), "values": deepcopy(DEFAULT_VALUES), "history": []}


def expected_type(category: str, key: str) -> str:
    explicit = FIELD_METADATA.get(category, {}).get(key, {}).get("type")
    if explicit:
        return str(explicit)
    default = DEFAULT_VALUES.get(category, {}).get(key)
    if isinstance(default, bool):
        return "boolean"
    if isinstance(default, int):
        return "integer"
    if isinstance(default, float):
        return "number"
    return "string"


def coerce_boolean(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if value in (0, "0", "false", "False", "off", "OFF"):
        return False
    if value in (1, "1", "true", "True", "on", "ON"):
        return True
    return value


def normalize_values(category: str, values: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(values)
    for key in DEFAULT_VALUES.get(category, {}):
        if key in normalized and expected_type(category, key) == "boolean":
            normalized[key] = coerce_boolean(normalized[key])
    return normalized


def normalize_state(state: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    changed = False
    values = state.get("values")
    if not isinstance(values, dict):
        return initial_state(), True
    for category, defaults in DEFAULT_VALUES.items():
        category_values = values.get(category)
        if not isinstance(category_values, dict):
            values[category] = deepcopy(defaults)
            changed = True
            continue
        normalized = normalize_values(category, category_values)
        for key, default in defaults.items():
            if key not in normalized:
                normalized[key] = deepcopy(default)
                changed = True
        if normalized != category_values:
            values[category] = normalized
            changed = True
    return state, changed


class ConfigStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        if not STATE_PATH.exists():
            self._write(initial_state())

    def _read(self) -> dict[str, Any]:
        try:
            value = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            value = initial_state()
        state = value if isinstance(value, dict) else initial_state()
        state, changed = normalize_state(state)
        if changed:
            self._write(state)
        return state

    def _write(self, state: dict[str, Any]) -> None:
        temp = STATE_PATH.with_suffix(".tmp")
        temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(STATE_PATH)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._read())

    def save(self, category: str, values: dict[str, Any], expected_revision: int) -> dict[str, Any]:
        with self._lock:
            state = self._read()
            if int(state.get("revision", 0)) != expected_revision:
                raise ConflictError("設定が別の画面またはプロセスで更新されています。再読込してください。")
            normalized = normalize_values(category, values)
            errors = validate_values(category, normalized)
            if errors:
                raise ValidationError(errors)
            before = deepcopy(state["values"].get(category, {}))
            state["values"][category] = deepcopy(normalized)
            state["revision"] = expected_revision + 1
            state["updated_at"] = utc_now()
            state.setdefault("history", []).insert(0, {"revision": state["revision"], "category": category, "saved_at": state["updated_at"], "before": before, "after": deepcopy(normalized)})
            state["history"] = state["history"][:30]
            self._write(state)
            return deepcopy(state)


class ConflictError(RuntimeError):
    pass


class ValidationError(ValueError):
    def __init__(self, errors: list[dict[str, str]]) -> None:
        super().__init__("設定内容にエラーがあります。")
        self.errors = errors


def metadata_for(category: str, values: dict[str, Any]) -> list[dict[str, Any]]:
    definitions = FIELD_METADATA.get(category, {})
    result: list[dict[str, Any]] = []
    for key, value in values.items():
        meta = deepcopy(definitions.get(key, {}))
        meta.setdefault("label", key.replace("_", " "))
        meta.setdefault("type", expected_type(category, key))
        meta.update({"key": key, "value": value, "source_file": f"{category}.yaml", "reload_policy": meta.get("reload_policy", "restart")})
        result.append(meta)
    return result


def validate_values(category: str, values: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if category not in DEFAULT_VALUES:
        return [{"field": "category", "message": "未対応の設定カテゴリです。"}]
    expected = DEFAULT_VALUES[category]
    for key, expected_value in expected.items():
        if key not in values:
            errors.append({"field": key, "message": "必須項目です。"})
            continue
        value = values[key]
        field_type = expected_type(category, key)
        if field_type == "boolean" and not isinstance(value, bool):
            errors.append({"field": key, "message": "オンまたはオフを指定してください。"})
        elif field_type == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
            errors.append({"field": key, "message": "整数で入力してください。"})
        elif field_type in {"string", "select", "reference", "path"} and not isinstance(value, str):
            errors.append({"field": key, "message": "文字列で入力してください。"})
        elif isinstance(expected_value, float) and not isinstance(value, (int, float)):
            errors.append({"field": key, "message": "数値で入力してください。"})
    if category == "speech" and isinstance(values.get("speaker_id"), int) and not isinstance(values.get("speaker_id"), bool) and values["speaker_id"] < 0:
        errors.append({"field": "speaker_id", "message": "0以上を指定してください。"})
    return errors


class ConfigConsoleService:
    def __init__(self, store: ConfigStore) -> None:
        self.store = store

    def manifest(self) -> dict[str, Any]:
        state = self.store.snapshot()
        return {"root": "config/index.yaml", "revision": state["revision"], "updated_at": state["updated_at"], "categories": CATEGORY_DEFINITIONS}

    def category(self, category: str) -> dict[str, Any]:
        state = self.store.snapshot()
        values = state["values"].get(category)
        if values is None:
            raise KeyError(category)
        definition = next(item for item in CATEGORY_DEFINITIONS if item["id"] == category)
        errors = validate_values(category, values)
        return {"category": definition, "revision": state["revision"], "updated_at": state["updated_at"], "fields": metadata_for(category, values), "values": values, "validation": {"valid": not errors, "errors": errors}}

    def validate(self, payload: dict[str, Any]) -> dict[str, Any]:
        category = str(payload.get("category") or "")
        values = payload.get("values")
        if not isinstance(values, dict):
            raise ValidationError([{"field": "values", "message": "設定値が不正です。"}])
        normalized = normalize_values(category, values)
        errors = validate_values(category, normalized)
        return {"valid": not errors, "errors": errors, "values": normalized, "reload_plan": reload_plan(category)}

    def save(self, category: str, payload: dict[str, Any]) -> dict[str, Any]:
        values = payload.get("values")
        revision = payload.get("revision")
        if not isinstance(values, dict) or not isinstance(revision, int) or isinstance(revision, bool):
            raise ValidationError([{"field": "request", "message": "revisionとvaluesが必要です。"}])
        state = self.store.save(category, values, revision)
        return {"saved": True, "revision": state["revision"], "updated_at": state["updated_at"], "reload_plan": reload_plan(category)}

    def history(self) -> dict[str, Any]:
        state = self.store.snapshot()
        return {"history": state.get("history", []), "revision": state["revision"]}


def reload_plan(category: str) -> dict[str, Any]:
    policy = {"runtime": "restart", "character": "restart", "speech": "next_request", "memory": "restart", "services": "reconnect", "models": "restart", "llm": "next_request", "emotion": "next_request", "streaming": "reconnect", "plugins": "restart"}.get(category, "restart")
    messages = {"immediate": "保存後すぐに反映できます。", "next_request": "次回処理から反映されます。", "reconnect": "対象サービスの再接続が必要です。", "restart": "Coreの再起動後に反映されます。"}
    return {"policy": policy, "message": messages[policy]}


def handler_for(service: ConfigConsoleService) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "YuraConfigConsole/1.1"

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/health":
                self._json({"status": "ok", "service": "yura-config-console"})
            elif path == "/api/v1/config/manifest":
                self._call(service.manifest)
            elif path == "/api/v1/config/history":
                self._call(service.history)
            elif path.startswith("/api/v1/config/categories/"):
                category = path.rsplit("/", 1)[-1]
                self._call(lambda: service.category(category))
            else:
                self._static(path)

        def do_POST(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/api/v1/config/validate":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            payload = self._read_json()
            if payload is None:
                self._json({"error": {"code": "invalid_json", "message": "JSONが不正です。"}}, HTTPStatus.BAD_REQUEST)
                return
            self._call(lambda: service.validate(payload))

        def do_PUT(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if not path.startswith("/api/v1/config/categories/"):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            payload = self._read_json()
            if payload is None:
                self._json({"error": {"code": "invalid_json", "message": "JSONが不正です。"}}, HTTPStatus.BAD_REQUEST)
                return
            category = path.rsplit("/", 1)[-1]
            self._call(lambda: service.save(category, payload))

        def _call(self, callback: Any) -> None:
            try:
                value = callback()
            except KeyError:
                self._json({"error": {"code": "category_not_found", "message": "設定カテゴリが見つかりません。"}}, HTTPStatus.NOT_FOUND)
            except ConflictError as error:
                self._json({"error": {"code": "revision_conflict", "message": str(error)}}, HTTPStatus.CONFLICT)
            except ValidationError as error:
                self._json({"error": {"code": "validation_failed", "message": str(error), "details": error.errors}}, HTTPStatus.BAD_REQUEST)
            except (OSError, ValueError, TypeError) as error:
                self._json({"error": {"code": "server_error", "message": str(error)}}, HTTPStatus.INTERNAL_SERVER_ERROR)
            else:
                self._json(value)

        def _read_json(self) -> dict[str, Any] | None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return None
            if length < 1 or length > MAX_JSON_BYTES:
                return None
            try:
                value = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return None
            return value if isinstance(value, dict) else None

        def _json(self, value: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _static(self, path: str) -> None:
            relative = "index.html" if path == "/" else path.lstrip("/")
            target = (WEB_ROOT / relative).resolve()
            if WEB_ROOT.resolve() not in target.parents or not target.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            body = target.read_bytes()
            content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            if "/health" not in str(args):
                super().log_message(format, *args)

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description="Yura configuration console")
    parser.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8790")))
    args = parser.parse_args()
    service = ConfigConsoleService(ConfigStore())
    server = ThreadingHTTPServer((args.host, args.port), handler_for(service))
    print(f"Yura configuration console: http://{args.host}:{args.port}")
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
