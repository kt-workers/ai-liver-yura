from __future__ import annotations

import json

import pytest

from app.domain.activities import Activity, ActivityType
from app.ports.llm_roles import ResponseGeneratorRoleAdapter


class StubResponseGenerator:
    def __init__(self, response: str) -> None:
        self.response = response

    async def generate_response(self, activity: Activity) -> str:
        return self.response


def _activity() -> Activity:
    return Activity(
        activity_type=ActivityType.BEHAVIOR_PLANNING,
        goal="状況を評価する",
    )


@pytest.mark.asyncio
async def test_situation_evaluation_normalizes_runtime_conversation_alias() -> None:
    raw = json.dumps(
        {
            "activity_type": "conversation_with_user",
            "operation": "continue",
            "goal": "会話を続ける",
        },
        ensure_ascii=False,
    )
    adapter = ResponseGeneratorRoleAdapter(StubResponseGenerator(raw))

    normalized = json.loads(await adapter.evaluate(_activity()))

    assert normalized["activity_type"] == "conversation"
    assert normalized["operation"] == "discuss"
    assert normalized["goal"] == "会話を続ける"


@pytest.mark.asyncio
async def test_situation_evaluation_normalizes_fenced_conversation_alias() -> None:
    raw = """```json
{"activity_type":"conversation_with_user","operation":"start","goal":"話す"}
```"""
    adapter = ResponseGeneratorRoleAdapter(StubResponseGenerator(raw))

    normalized = json.loads(await adapter.evaluate(_activity()))

    assert normalized["activity_type"] == "conversation"
    assert normalized["operation"] == "discuss"


@pytest.mark.asyncio
async def test_situation_evaluation_preserves_plugin_activity() -> None:
    raw = json.dumps(
        {
            "activity_type": "plugin_activity",
            "operation": "start",
            "goal": "Pluginを開始する",
        },
        ensure_ascii=False,
    )
    adapter = ResponseGeneratorRoleAdapter(StubResponseGenerator(raw))

    assert await adapter.evaluate(_activity()) == raw


@pytest.mark.asyncio
async def test_situation_evaluation_preserves_invalid_json_for_schema_validation() -> None:
    raw = "not-json"
    adapter = ResponseGeneratorRoleAdapter(StubResponseGenerator(raw))

    assert await adapter.evaluate(_activity()) == raw


@pytest.mark.asyncio
async def test_character_role_does_not_apply_situation_normalization() -> None:
    raw = json.dumps(
        {
            "activity_type": "conversation_with_user",
            "operation": "continue",
        }
    )
    adapter = ResponseGeneratorRoleAdapter(StubResponseGenerator(raw))

    assert await adapter.generate_character_response(_activity()) == raw
