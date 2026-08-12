from __future__ import annotations

import json
from typing import Any

import pytest

from app.adapters.llm.openai_response_generator import OpenAIResponseGenerator
from app.domain.activities import Activity, ActivityType
from app.domain.character import CharacterProfile
from app.ports.structured_output import (
    StructuredOutputContract,
    StructuredOutputError,
)


class _PromptBuilder:
    def build_prompt(self, activity: Activity, character_profile: CharacterProfile) -> str:
        override = activity.context.get("plugin_prompt_override")
        return str(override or "structured prompt")


class _HttpResponse:
    def __init__(self, body: str) -> None:
        self._body = body

    def __enter__(self) -> _HttpResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body.encode("utf-8")


def _profile() -> CharacterProfile:
    return CharacterProfile(
        name="ゆら",
        personality="好奇心がある",
        speaking_style="自然体",
        streaming_style="落ち着いた雑談",
    )


def _generator() -> OpenAIResponseGenerator:
    return OpenAIResponseGenerator(
        model="gpt-test",
        api_key_env="YURA_TEST_OPENAI_KEY",
        timeout_seconds=5.0,
        fallback_response="fallback",
        character_profile=_profile(),
        prompt_builder=_PromptBuilder(),  # type: ignore[arg-type]
        base_url="https://example.test/v1",
    )


def _activity() -> Activity:
    return Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="reply",
        context={"plugin_prompt_override": "v2 prompt"},
    )


def _contract() -> StructuredOutputContract:
    return StructuredOutputContract(
        name="character_utterance_v2",
        schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["speech"],
            "properties": {"speech": {"type": "string"}},
        },
        strict=True,
    )


@pytest.mark.asyncio
async def test_generate_structured_uses_responses_text_json_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YURA_TEST_OPENAI_KEY", "test-key")
    captured: dict[str, Any] = {}

    def fake_urlopen(request: Any, *, timeout: float) -> _HttpResponse:
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data.decode("utf-8"))
        output = json.dumps({"speech": "うれしいよ。"}, ensure_ascii=False)
        return _HttpResponse(json.dumps({"output_text": output}, ensure_ascii=False))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    payload = await _generator().generate_structured(_activity(), _contract())

    assert payload == {"speech": "うれしいよ。"}
    assert captured["url"] == "https://example.test/v1/responses"
    body = captured["body"]
    assert body["model"] == "gpt-test"
    assert body["input"] == "v2 prompt"
    assert body["text"]["format"] == {
        "type": "json_schema",
        "name": "character_utterance_v2",
        "schema": dict(_contract().schema),
        "strict": True,
    }


@pytest.mark.asyncio
async def test_generate_structured_does_not_use_plain_fallback_when_key_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("YURA_TEST_OPENAI_KEY", raising=False)

    with pytest.raises(StructuredOutputError, match="API key"):
        await _generator().generate_structured(_activity(), _contract())


@pytest.mark.asyncio
async def test_generate_structured_fails_closed_on_non_object_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YURA_TEST_OPENAI_KEY", "test-key")

    def fake_urlopen(request: Any, *, timeout: float) -> _HttpResponse:
        return _HttpResponse(json.dumps({"output_text": "[]"}))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(StructuredOutputError, match="rootがobject"):
        await _generator().generate_structured(_activity(), _contract())
