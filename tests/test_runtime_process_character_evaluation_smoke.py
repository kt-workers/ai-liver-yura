from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yaml


_SITUATION_RESPONSE = json.dumps(
    {
        "decision": "continue_conversation",
        "activity_type": "conversation_with_user",
        "operation": "continue",
        "goal": "ユーザーとの通常会話を続ける",
        "constraints": {},
        "speech_act": "statement",
        "conversation_phase": "active",
        "initiative_level": 0.25,
        "negated": False,
        "hypothetical": False,
        "past_reference": False,
        "knowledge_question": False,
        "confidence": 0.94,
        "reason": "ordinary_conversation",
        "ongoing_input_decision": None,
        "semantic_equivalence": {
            "candidate_group": [],
            "intent": "unknown",
            "operation": "unknown",
            "goal": "unknown",
            "reasons": ["candidate_group_is_empty"],
        },
    },
    ensure_ascii=False,
)

_CHARACTER_RESPONSE = json.dumps(
    {
        "speech": "うん、話を続けよう。",
        "expression": "soft_smile",
        "gesture": None,
        "voice_intent": {
            "style": "neutral",
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
                "evidence": "通常会話として応答している",
            }
        ],
    },
    ensure_ascii=False,
)

_VALIDATOR_RESPONSE = json.dumps(
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
                "evidence": "通常会話として応答している",
            }
        ],
    },
    ensure_ascii=False,
)


class _FakeOllamaHandler(BaseHTTPRequestHandler):
    prompts: list[str] = []
    lock = threading.Lock()

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        body_length = int(self.headers.get("Content-Length", "0"))
        request_body = self.rfile.read(body_length).decode("utf-8")
        payload = json.loads(request_body)
        prompt = str(payload.get("prompt", ""))
        with self.lock:
            self.prompts.append(prompt)

        if "あなたはSituation Evaluatorです" in prompt:
            response_text = _SITUATION_RESPONSE
        elif "あなたはCharacter LLMです" in prompt:
            response_text = _CHARACTER_RESPONSE
        elif "あなたはResponse Validatorです" in prompt:
            response_text = _VALIDATOR_RESPONSE
        else:
            response_text = "other"

        response_body = json.dumps(
            {"response": response_text}, ensure_ascii=False
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def _write_smoke_config(
    repo_root: Path,
    temp_root: Path,
    ollama_base_url: str,
) -> tuple[Path, Path, Path]:
    trace_path = temp_root / "runtime_trace.jsonl"
    debug_path = temp_root / "runtime_debug.jsonl"
    override_path = temp_root / "runtime-smoke.yaml"
    manifest_path = temp_root / "index.yaml"

    imports = {
        "app": repo_root / "config/runtime.yaml",
        "trace": repo_root / "config/runtime.yaml",
        "input_receivers": repo_root / "config/runtime.yaml",
        "confirmation": repo_root / "config/runtime.yaml",
        "character": repo_root / "config/character.yaml",
        "speech": repo_root / "config/speech.yaml",
        "memory": repo_root / "config/memory.yaml",
        "services": repo_root / "config/services.yaml",
        "models": repo_root / "config/models.yaml",
        "response_generator": repo_root / "config/llm.yaml",
        "llm_roles": repo_root / "config/llm.yaml",
        "topic_classifier": repo_root / "config/llm.yaml",
        "emotion_appraisal": repo_root / "config/emotion.yaml",
        "plugins": repo_root / "config/plugins/index.yaml",
    }
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "imports": {
                    key: str(path.resolve()) for key, path in imports.items()
                },
                "environments": {"runtime-smoke": str(override_path)},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    overrides = [
        {"path": "services.ollama.base_url", "value": ollama_base_url},
        {"path": "services.ollama.timeout_seconds", "value": 5.0},
        {"path": "response_generator.model", "value": "ollama_chat"},
        {
            "path": "llm_roles.situation_evaluator.model",
            "value": "ollama_chat",
        },
        {"path": "llm_roles.character.model", "value": "ollama_chat"},
        {
            "path": "llm_roles.response_validator.model",
            "value": "ollama_chat",
        },
        {"path": "topic_classifier.model", "value": "ollama_chat"},
        {"path": "speech.enabled", "value": False},
        {"path": "memory.topic_memory.enabled", "value": False},
        {"path": "memory.relationship_memory.enabled", "value": False},
        {"path": "memory.agent_memory.enabled", "value": False},
        {"path": "emotion_appraisal.enabled", "value": False},
        {"path": "trace.level", "value": "DEBUG"},
        {"path": "trace.format", "value": "jsonl"},
        {"path": "trace.file_path", "value": str(trace_path)},
        {"path": "trace.debug_file_enabled", "value": True},
        {"path": "trace.debug_file_path", "value": str(debug_path)},
        {"path": "trace.log_llm_prompts", "value": True},
        {"path": "trace.log_llm_responses", "value": True},
        {"path": "trace.log_user_input", "value": True},
        {"path": "input_receivers.timer.enabled", "value": False},
    ]
    override_path.write_text(
        yaml.safe_dump(
            {"overrides": overrides}, allow_unicode=True, sort_keys=False
        ),
        encoding="utf-8",
    )
    return manifest_path, trace_path, debug_path


def _prompt_sequence() -> list[str]:
    with _FakeOllamaHandler.lock:
        return list(_FakeOllamaHandler.prompts)


def _conversation_pipeline_completed() -> bool:
    prompts = _prompt_sequence()
    situation_index = next(
        (
            index
            for index, prompt in enumerate(prompts)
            if "あなたはSituation Evaluatorです" in prompt and "ふむふむ" in prompt
        ),
        None,
    )
    if situation_index is None:
        return False
    later_prompts = prompts[situation_index + 1 :]
    return any("あなたはCharacter LLMです" in prompt for prompt in later_prompts) and any(
        "あなたはResponse Validatorです" in prompt for prompt in later_prompts
    )


def test_app_process_accepts_runtime_conversation_alias_and_updates_drive(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    _FakeOllamaHandler.prompts = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOllamaHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    manifest_path, trace_path, debug_path = _write_smoke_config(
        repo_root,
        tmp_path,
        f"http://127.0.0.1:{server.server_port}",
    )
    environment = os.environ.copy()
    environment.update(
        {
            "AI_LIVER_CONFIG_PATH": str(manifest_path),
            "AI_LIVER_CONFIG_ENV": "runtime-smoke",
            "YURA_WEB_CONVERSATION_ENABLED": "0",
            "PYTHONUNBUFFERED": "1",
        }
    )

    process = subprocess.Popen(
        [sys.executable, "-m", "app"],
        cwd=repo_root,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout = ""
    stderr = ""
    try:
        assert process.stdin is not None
        process.stdin.write("ふむふむ\n")
        process.stdin.flush()

        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            if process.poll() is not None or _conversation_pipeline_completed():
                break
            time.sleep(0.05)

        assert process.poll() is None, "app process terminated before conversation completed"
        assert _conversation_pipeline_completed(), (
            "conversation did not pass Situation, Character, and Validator roles"
        )

        process.stdin.write("exit\n")
        process.stdin.flush()
        stdout, stderr = process.communicate(timeout=10.0)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                stdout, stderr = process.communicate(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate(timeout=5.0)
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5.0)

    assert process.returncode == 0, f"stdout={stdout}\nstderr={stderr}"
    assert "ゆらを起動しました" in stdout
    assert "終了しました。" in stdout

    trace_text = trace_path.read_text(encoding="utf-8")
    debug_text = debug_path.read_text(encoding="utf-8")
    combined_trace = trace_text + "\n" + debug_text
    assert "ordinary_conversation" in combined_trace
    assert "schema_validation_failed" not in combined_trace
    assert '"input_kind": "acknowledgement"' in combined_trace
    assert '"stimulus_scale": 0.25' in combined_trace
