"""Reflection固有factoryと汎用Providerの共有を検証する。"""

import asyncio
import json
from dataclasses import replace
from typing import Any

import pytest

from app.adapters.llm.memory_reflection import (
    PROPOSAL_FORMAT_NAME,
    SUPPORT_FORMAT_NAME,
    reflection_proposal_openai_role_config,
    reflection_support_openai_role_config,
)
from app.adapters.llm.openai_responses import OpenAIResponsesAdapter
from app.domain.llm import LLMModelClass, LLMReasoningEffort, LLMRoleStatus
from app.domain.memory_reflection.llm_roles import (
    PROPOSAL_INPUT_SCHEMA,
    PROPOSAL_OUTPUT_SCHEMA,
    PROPOSAL_ROLE_ID,
    SUPPORT_INPUT_SCHEMA,
    SUPPORT_OUTPUT_SCHEMA,
    SUPPORT_ROLE_ID,
    build_proposal_request,
    build_support_request,
    parse_proposals,
    parse_support,
    proposal_to_wire,
)
from app.domain.memory_reflection.schemas import proposal_output_schema, support_output_schema
from tests.adapters.llm.test_openai_responses import FakeClient, FakeResponse
from tests.domain.memory_reflection.test_llm_roles import (
    candidate,
    role_policy,
    snapshot,
    support_wire,
)
from tests.domain.memory_reflection.test_memory_reflection import NOW


@pytest.mark.asyncio
async def test_both_roles_share_generic_adapter_with_exact_configs() -> None:
    models = {LLMModelClass.BALANCED: "test-model-explicit"}
    reasoning = {LLMReasoningEffort.MEDIUM: "medium"}
    p = reflection_proposal_openai_role_config(models, reasoning_by_effort=reasoning)
    s = reflection_support_openai_role_config(models, reasoning_by_effort=reasoning)
    assert (p.role_id, p.input_schema_id, p.output_schema_id) == (
        PROPOSAL_ROLE_ID,
        PROPOSAL_INPUT_SCHEMA,
        PROPOSAL_OUTPUT_SCHEMA,
    )
    assert (s.role_id, s.input_schema_id, s.output_schema_id) == (
        SUPPORT_ROLE_ID,
        SUPPORT_INPUT_SCHEMA,
        SUPPORT_OUTPUT_SCHEMA,
    )
    assert p.output_json_schema == proposal_output_schema()
    assert s.output_json_schema == support_output_schema()
    assert p.provider_output_format_name == PROPOSAL_FORMAT_NAME
    assert s.provider_output_format_name == SUPPORT_FORMAT_NAME != PROPOSAL_FORMAT_NAME
    assert p.model_policies[LLMModelClass.BALANCED].model == "test-model-explicit"
    policy = role_policy()
    policy = replace(
        policy,
        proposal_execution=replace(policy.proposal_execution, temperature_normalized=None),
        support_execution=replace(policy.support_execution, temperature_normalized=None),
    )
    client = FakeClient(
        FakeResponse(json.dumps({"proposals": [proposal_to_wire(candidate())]})),
        FakeResponse(json.dumps(support_wire())),
    )
    adapter = OpenAIResponsesAdapter(client, (p, s), now=lambda: NOW)
    first, second = await asyncio.gather(
        adapter.invoke(build_proposal_request(snapshot(), created_at=NOW, policy=policy)),
        adapter.invoke(
            build_support_request(snapshot(), candidate(), created_at=NOW, policy=policy)
        ),
    )
    assert first.status is second.status is LLMRoleStatus.SUCCEEDED
    assert first.output is not None and second.output is not None
    assert parse_proposals(first.output.value, snapshot(), policy.operational) == (candidate(),)
    assert (
        parse_support(second.output.value, snapshot(), candidate(), policy.operational).proposal_id
        == candidate().proposal_id
    )
    assert len(client.calls) == 2
    formats = [call["text"] for call in client.calls]
    assert all("strict" in str(f) for f in formats)


@pytest.mark.parametrize(
    "models,reasoning",
    [
        ({}, {LLMReasoningEffort.LOW: "low"}),
        ({LLMModelClass.BALANCED: "model"}, {}),
        ({LLMModelClass.MULTIMODAL: "model"}, {LLMReasoningEffort.LOW: "low"}),
        ({"invalid": "model"}, {LLMReasoningEffort.LOW: "low"}),
        ({LLMModelClass.BALANCED: ""}, {LLMReasoningEffort.LOW: "low"}),
        ({LLMModelClass.BALANCED: "model"}, {"invalid": "low"}),
    ],
)
def test_unsupported_mapping_rejected(models: Any, reasoning: Any) -> None:
    for factory in (reflection_proposal_openai_role_config, reflection_support_openai_role_config):
        with pytest.raises(ValueError):
            factory(models, reasoning_by_effort=reasoning)
