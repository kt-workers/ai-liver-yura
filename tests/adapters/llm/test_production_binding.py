import asyncio
import json
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import openai
import pytest

from app.adapters.llm import openai_responses, production
from app.adapters.llm.openai_responses import OpenAIResponsesAdapter, OpenAIResponsesRoleConfig
from app.adapters.llm.production import UnavailableLLMRolePort, create_openai_port_from_environment
from app.domain.llm import (
    LLMActivationPolicy,
    LLMFailureCode,
    LLMFailurePolicy,
    LLMModelClass,
    LLMRoleDescriptor,
    LLMRoleStatus,
    validate_role_exchange,
)
from tests.adapters.llm.test_openai_responses import (
    FakeClient,
    FakeResponse,
    make_config,
    make_request,
)


def role() -> LLMRoleDescriptor:
    return LLMRoleDescriptor(
        "meaning",
        "試験用の論理役割",
        "meaning.input.v1",
        "meaning.output.v1",
        "candidate",
        LLMActivationPolicy.REQUIRED,
        LLMFailurePolicy.FAIL_CLOSED,
        make_request().execution_policy,
    )


def environment(monkeypatch: pytest.MonkeyPatch, configured: bool) -> None:
    # 実環境の資格情報を読み書きせず、接続選択だけを再現する。
    stub = SimpleNamespace(environ={"OPENAI_API_KEY": "試験用の非秘密文字列"} if configured else {})
    monkeypatch.setattr(production, "os", stub)
    monkeypatch.setattr(openai_responses, "os", stub)


def test_unconfigured_factory_requires_no_provider_config_or_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment(monkeypatch, False)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("未構成経路でSDKを初期化してはなりません")

    monkeypatch.setattr(openai, "AsyncOpenAI", forbidden)
    port = create_openai_port_from_environment((role(),))
    assert isinstance(port, UnavailableLLMRolePort)
    request = make_request(model_class=LLMModelClass.DEEP_REASONING)
    outcome = asyncio.run(port.invoke(request))
    assert outcome.status is LLMRoleStatus.FAILED
    assert outcome.failure is not None
    assert outcome.failure.code is LLMFailureCode.PROVIDER_UNAVAILABLE
    assert outcome.failure.retryable is False
    assert outcome.output is None and outcome.execution_provenance is None
    assert outcome.started_at is None
    assert outcome.attempt_count == 0
    assert outcome.token_usage.to_dict() == {"input_tokens": 0, "output_tokens": 0}
    assert (outcome.request_id, outcome.role_id, outcome.trace_id) == (
        request.request_id,
        request.role_id,
        request.trace_id,
    )
    assert outcome.revisions is request.revisions
    assert outcome.model_class is request.execution_policy.model_class
    assert outcome.completed_at.tzinfo is timezone.utc
    assert validate_role_exchange(role(), request, outcome) is None
    encoded = json.dumps(outcome.to_dict(), ensure_ascii=False, allow_nan=False)
    assert "こんにちは" not in encoded
    assert "試験用の非秘密文字列" not in encoded


@pytest.mark.parametrize("invalid", ["role", "schema"])
def test_logical_violation_precedes_unavailable(invalid: str) -> None:
    request = make_request(
        role_id="unknown" if invalid == "role" else "meaning",
        input_schema_id="unknown" if invalid == "schema" else "meaning.input.v1",
    )
    outcome = asyncio.run(UnavailableLLMRolePort((role(),)).invoke(request))
    assert outcome.failure is not None
    assert outcome.failure.code is LLMFailureCode.POLICY_VIOLATION
    assert outcome.output is None and outcome.attempt_count == 0


def test_duplicate_registration_rejected() -> None:
    with pytest.raises(ValueError, match="重複"):
        UnavailableLLMRolePort((role(), role()))


def test_configured_factory_uses_existing_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    environment(monkeypatch, True)
    client = FakeClient(FakeResponse('{"ok":true}'))
    constructions: list[dict[str, Any]] = []

    def sdk(**kwargs: Any) -> object:
        constructions.append(kwargs)
        return SimpleNamespace(responses=client)

    monkeypatch.setattr(openai, "AsyncOpenAI", sdk)
    port = create_openai_port_from_environment((role(),), role_configs=(make_config(),))
    assert isinstance(port, OpenAIResponsesAdapter)
    assert len(constructions) == 1
    outcome = asyncio.run(port.invoke(make_request()))
    assert outcome.status is LLMRoleStatus.SUCCEEDED
    assert len(client.calls) == 1
    unsupported = make_request(max_output_tokens=100, temperature_normalized=0.5)
    rejected = asyncio.run(port.invoke(unsupported))
    assert rejected.failure is not None
    assert rejected.failure.code is LLMFailureCode.POLICY_VIOLATION
    assert len(client.calls) == 1


@pytest.mark.parametrize("case", ["missing", "role", "schema", "duplicate", "sdk"])
def test_configured_errors_never_fallback(monkeypatch: pytest.MonkeyPatch, case: str) -> None:
    environment(monkeypatch, True)

    def failing_sdk(**kwargs: object) -> object:
        if case == "sdk":
            raise RuntimeError("試験用の初期化失敗")
        return SimpleNamespace(responses=FakeClient())

    monkeypatch.setattr(openai, "AsyncOpenAI", failing_sdk)
    configs: tuple[OpenAIResponsesRoleConfig, ...] = (make_config(),)
    if case == "role":
        configs = (make_config(role_id="other"),)
    elif case == "schema":
        configs = (make_config(input_schema_id="other"),)
    elif case == "duplicate":
        configs = configs + configs
    with pytest.raises(RuntimeError if case == "sdk" else ValueError):
        create_openai_port_from_environment(
            (role(),), role_configs=None if case == "missing" else configs
        )


def test_existing_required_factory_still_rejects_missing_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment(monkeypatch, False)
    with pytest.raises(ValueError):
        OpenAIResponsesAdapter.from_environment((make_config(),))


def test_request_domain_invariants_are_not_redefined() -> None:
    with pytest.raises(ValueError):
        replace(make_request().execution_policy, max_output_tokens=0)
    with pytest.raises(ValueError):
        replace(make_request(), created_at=datetime(2026, 9, 5))
