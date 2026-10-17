"""任意LLMの未接続が統合Brain構成を壊さないことを検証する。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import openai
import pytest

from app.adapters.llm import connections
from app.adapters.llm.connections import OpenAIResponsesConnectionAdapter
from app.adapters.llm.production import UnavailableLLMRolePort
from app.config.llm_connections import LLMConnectionConfig
from app.domain.llm import LLMFailureCode, LLMRoleStatus
from tests.adapters.llm.test_openai_responses import make_request
from tests.adapters.llm.test_production_binding import role


def connection() -> LLMConnectionConfig:
    descriptor = role()
    execution = descriptor.default_execution_policy
    return LLMConnectionConfig(
        "core-llm",
        "openai_responses",
        {
            "model_mappings": [
                {
                    "model_class": execution.model_class.value,
                    "mapping_id": "mapping-1",
                    "mapping_revision": 1,
                    "model": "test-model",
                    "reasoning_by_effort": {
                        execution.reasoning_effort.value: "low",
                    },
                },
            ],
        },
    )


def test_missing_credential_preserves_registered_roles_and_reports_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(connections, "os", SimpleNamespace(environ={}))

    def forbidden(**kwargs: object) -> object:
        pytest.fail("外部提供先が未接続のときにSDKを生成してはなりません")

    monkeypatch.setattr(openai, "AsyncOpenAI", forbidden)
    descriptor = replace(role(), role_id="input_meaning")

    async def scenario() -> None:
        port, close = await OpenAIResponsesConnectionAdapter().connect(
            connection(), (descriptor,)
        )
        assert isinstance(port, UnavailableLLMRolePort)
        result = await port.invoke(make_request(role_id="input_meaning"))
        assert result.status is LLMRoleStatus.FAILED
        assert result.failure is not None
        assert result.failure.code is LLMFailureCode.PROVIDER_UNAVAILABLE
        assert result.output is None
        await close()
        await close()

    asyncio.run(scenario())


def test_invalid_mapping_is_not_converted_to_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(connections, "os", SimpleNamespace(environ={}))

    async def scenario() -> None:
        invalid = LLMConnectionConfig(
            "core-llm", "openai_responses", {"model_mappings": []}
        )
        with pytest.raises(ValueError):
            await OpenAIResponsesConnectionAdapter().connect(
                invalid, (replace(role(), role_id="input_meaning"),)
            )

    asyncio.run(scenario())
