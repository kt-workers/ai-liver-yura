import asyncio
import json
from dataclasses import replace
from typing import Any

import pytest

from app.adapters.llm.appraisal import (
    APPRAISAL_PROVIDER_FORMAT_NAME,
    appraisal_openai_role_config,
)
from app.adapters.llm.openai_responses import OpenAIResponsesAdapter, OpenAIResponsesModelPolicy
from app.adapters.llm.production import UnavailableLLMRolePort, create_openai_port_from_environment
from app.config.appraisal import load_appraisal_config
from app.domain.appraisal.deep import DeepAppraisalContext, build_deep_request, descriptor
from app.domain.appraisal.schemas import appraisal_instructions, appraisal_output_schema
from app.domain.llm import (
    LLMFailureCode,
    LLMFailurePolicy,
    LLMModelClass,
    LLMReasoningEffort,
    LLMRoleStatus,
)
from tests.adapters.llm.test_openai_responses import FakeClient, FakeResponse
from tests.config.test_appraisal import SOURCE
from tests.domain.appraisal.test_appraisal_paths import NOW, event, output, state


def mapping() -> OpenAIResponsesModelPolicy:
    return OpenAIResponsesModelPolicy(
        "deployment:test",
        7,
        "test-provider-model",
        {LLMReasoningEffort.MEDIUM: "medium"},
        provider_max_output_tokens=2048,
    )


def test_helper_preserves_mapping_and_role() -> None:
    supplied = mapping()
    config = appraisal_openai_role_config({LLMModelClass.BALANCED: supplied})
    assert config.model_policies[LLMModelClass.BALANCED] is supplied
    assert (
        supplied.mapping_id,
        supplied.mapping_revision,
        supplied.provider_max_output_tokens,
    ) == (
        "deployment:test",
        7,
        2048,
    )
    assert (config.role_id, config.input_schema_id, config.output_schema_id) == (
        "subjective_appraisal",
        "yura.subjective-appraisal.request.v1",
        "yura.subjective-appraisal.candidate.v1",
    )
    assert config.provider_output_format_name == APPRAISAL_PROVIDER_FORMAT_NAME
    assert config.failure_policy is LLMFailurePolicy.SKIP_OPTIONAL
    assert config.output_json_schema == appraisal_output_schema()
    assert config.instructions == appraisal_instructions()
    for model in (LLMModelClass.FAST, LLMModelClass.BALANCED, LLMModelClass.DEEP_REASONING):
        assert appraisal_openai_role_config({model: supplied}).model_policies[model] is supplied


@pytest.mark.parametrize(
    "value",
    [
        {},
        {LLMModelClass.MULTIMODAL: mapping()},
        {"balanced": mapping()},
        {LLMModelClass.BALANCED: object()},
    ],
)
def test_invalid_mapping(value: Any) -> None:
    with pytest.raises(ValueError):
        appraisal_openai_role_config(value)


@pytest.mark.parametrize("case", ["supported", "reasoning", "limit", "class"])
def test_generic_adapter_uses_production_policy(case: str) -> None:
    config = load_appraisal_config(SOURCE)
    supplied = mapping()
    if case == "reasoning":
        supplied = replace(supplied, reasoning_by_effort={LLMReasoningEffort.LOW: "low"})
    elif case == "limit":
        supplied = replace(supplied, provider_max_output_tokens=1535)
    key = LLMModelClass.FAST if case == "class" else LLMModelClass.BALANCED
    client = FakeClient(FakeResponse(json.dumps(output())))
    adapter = OpenAIResponsesAdapter(client, (appraisal_openai_role_config({key: supplied}),))
    request = build_deep_request(
        event(),
        None,
        state(),
        DeepAppraisalContext(()),
        request_id="request:production",
        trace_id="trace:1",
        created_at=NOW,
        policy=config.appraisal_policy,
    )
    result = asyncio.run(adapter.invoke(request))
    if case == "supported":
        assert result.status is LLMRoleStatus.SUCCEEDED
        assert len(client.calls) == 1
        assert client.calls[0]["model"] == supplied.model
        assert client.calls[0]["max_output_tokens"] == 1536
        assert client.calls[0]["reasoning"] == {"effort": "medium"}
    else:
        assert not client.calls
        assert result.failure is not None
        assert result.failure.code is LLMFailureCode.POLICY_VIOLATION


def test_unavailable_and_configured_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    roles = (descriptor(load_appraisal_config(SOURCE).appraisal_policy),)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert isinstance(create_openai_port_from_environment(roles), UnavailableLLMRolePort)
    monkeypatch.setenv("OPENAI_API_KEY", "test-placeholder")
    with pytest.raises(ValueError):
        create_openai_port_from_environment(roles)
    role = appraisal_openai_role_config({LLMModelClass.BALANCED: mapping()})
    with pytest.raises(ValueError):
        create_openai_port_from_environment(roles, role_configs=(replace(role, role_id="other"),))
    monkeypatch.setattr(
        OpenAIResponsesAdapter,
        "from_environment",
        lambda configs: OpenAIResponsesAdapter(FakeClient(), configs),
    )
    assert isinstance(
        create_openai_port_from_environment(roles, role_configs=(role,)), OpenAIResponsesAdapter
    )
