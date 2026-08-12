from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

import pytest

from app.adapters.llm import OpenAIResponseGenerator
from app.adapters.prompt import SimplePromptBuilder
from app.domain.activities import Activity, ActivityType
from app.domain.character import CharacterProfile
from app.ports.structured_output import (
    StructuredOutputContract,
    StructuredOutputGenerationError,
)


class _FakeHttpResponse:
    def __init__(self, body: dict[str, Any]) -> None:
        self._body = json.dumps(body, ensure_ascii=False).encode("utf-8")

    def __enter__(self) -> "_FakeHttpResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _generator() -> OpenAIResponseGenerator:
    return OpenAIResponseGenerator(
        model="gpt-5.4-mini",
        api_key_env="TEST_OPENAI_API_KEY",
        timeout_seconds=3.0,
        fallback_response="legacy fallback",
        character_profile=CharacterProfile(
            name="ゆら",
            personality="穏やか",
            speaking_style="自然",
            streaming_style="自然",
        ),
        prompt_builder=SimplePromptBuilder(),
    )


def _activity() -> Activity:
    return Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="structured test",
        context={
            "plugin_prompt_override": "structured prompt",
            "llm_role": "character_semantic_verifier",
        },
    )


def _contract() -> StructuredOutputContract:
    return StructuredOutputContract(
        name="test_contract",
        schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["ok"],
            "properties": {"ok": {"type": "boolean"}},
        },
    )


@pytest.mark.asyncio
async def test_openai_structured_output_sends_strict_json_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: dict[str, object] = {}

    def fake_urlopen(
        request: urllib.request.Request,
        timeout: float,
    ) -> _FakeHttpResponse:
        sent["body"] = json.loads(request.data or b"{}")
        sent["timeout"] = timeout
        return _FakeHttpResponse(
            {
                "status": "completed",
                "output_text": json.dumps({"ok": True}),
            }
        )

    monkeypatch.setenv("TEST_OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = await _generator().generate_structured_response(_activity(), _contract())

    assert result == {"ok": True}
    assert sent["timeout"] == 3.0
    body = sent["body"]
    assert isinstance(body, dict)
    assert body["model"] == "gpt-5.4-mini"
    assert body["text"] == {
        "format": {
            "type": "json_schema",
            "name": "test_contract",
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["ok"],
                "properties": {"ok": {"type": "boolean"}},
            },
            "strict": True,
        }
    }


@pytest.mark.asyncio
async def test_structured_output_does_not_fall_back_to_legacy_text_on_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(
        request: urllib.request.Request,
        timeout: float,
    ) -> _FakeHttpResponse:
        del request, timeout
        raise urllib.error.URLError("network down")

    monkeypatch.setenv("TEST_OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(StructuredOutputGenerationError):
        await _generator().generate_structured_response(_activity(), _contract())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response_body",
    [
        {"status": "incomplete", "output_text": json.dumps({"ok": True})},
        {"status": "completed", "output_text": "not-json"},
        {"status": "completed", "output_text": json.dumps([{"ok": True}])},
        {"status": "completed", "output": []},
    ],
)
async def test_structured_output_fails_closed_for_non_object_or_incomplete_response(
    response_body: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(
        request: urllib.request.Request,
        timeout: float,
    ) -> _FakeHttpResponse:
        del request, timeout
        return _FakeHttpResponse(response_body)

    monkeypatch.setenv("TEST_OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(StructuredOutputGenerationError):
        await _generator().generate_structured_response(_activity(), _contract())


def test_structured_output_contract_rejects_non_object_schema() -> None:
    with pytest.raises(ValueError):
        StructuredOutputContract(name="bad", schema={"type": "array"})
