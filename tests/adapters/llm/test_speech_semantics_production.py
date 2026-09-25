"""本番Role登録、wire往復、既存意味検査と失敗保全の検証。"""

import asyncio
import json
from copy import deepcopy
from dataclasses import replace
from typing import Any

import pytest
from jsonschema import Draft202012Validator, ValidationError, validate

from app.adapters.llm.openai_responses import OpenAIResponsesAdapter, OpenAIResponsesModelPolicy
from app.adapters.llm.speech_semantics import (
    SpeechSemanticsProviderPort,
    speech_semantics_openai_role_config,
    speech_semantics_provider_descriptor,
)
from app.domain.contracts.common import freeze_json, thaw_json
from app.domain.llm import (
    LLMFailureCode,
    LLMModelClass,
    LLMReasoningEffort,
    LLMRoleFailure,
    LLMRoleRequest,
    LLMRoleResult,
    LLMRoleStatus,
    StructuredPayload,
    validate_role_exchange,
)
from app.domain.speech_semantics.planner import (
    OUTPUT_SCHEMA,
    build_request,
    descriptor,
    parse_candidate,
)
from app.domain.speech_semantics.schemas import (
    PROVIDER_OUTPUT_SCHEMA,
    decode_speech_semantics_output,
    speech_semantics_instructions,
    speech_semantics_output_schema,
)
from tests.adapters.llm.test_openai_responses import FakeClient, FakeResponse
from tests.domain.speech_semantics.test_speech_semantics import (
    NOW,
    candidate_json,
    context,
    policy,
    result_for,
)


def encode(value: Any) -> Any:
    if isinstance(value, dict):
        return {"members": [{"key": k, "value": encode(v)} for k, v in value.items()]}
    if isinstance(value, list):
        return [encode(v) for v in value]
    return value


def wire() -> dict[str, Any]:
    value: Any = candidate_json()
    for proposition in value["propositions"]:
        proposition["value"] = encode(proposition["value"])
    return value  # type: ignore[no-any-return]


def request() -> LLMRoleRequest:
    return build_request(
        context(), request_id="request", trace_id="trace", created_at=NOW, policy=policy()
    )


def mapping(model: str = "test-model") -> OpenAIResponsesModelPolicy:
    return OpenAIResponsesModelPolicy(
        "deployment.mapping",
        7,
        model,
        {LLMReasoningEffort.MEDIUM: "medium"},
        provider_max_output_tokens=2048,
    )


def decode(value: Any) -> Any:
    return thaw_json(
        decode_speech_semantics_output(
            freeze_json(value),
            created_at=NOW,
            bounds_policy=policy().bounds_policy,
        )
    )


def test_schema_closed_objects_and_registration() -> None:
    schema = speech_semantics_output_schema()
    Draft202012Validator.check_schema(schema)

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(schema)
    for model in ("test-model-one", "test-model-two"):
        supplied = mapping(model)
        config = speech_semantics_openai_role_config({LLMModelClass.BALANCED: supplied})
        assert config.model_policies[LLMModelClass.BALANCED] is supplied
        assert config.output_schema_id == PROVIDER_OUTPUT_SCHEMA != OUTPUT_SCHEMA
        assert config.role_id == descriptor(policy()).role_id
        assert config.output_json_schema == schema
        assert config.instructions == speech_semantics_instructions()
        assert model not in config.instructions
        assert config.provider_output_format_name == "speech_semantics_candidate_wire_v1"
    changed = speech_semantics_output_schema()
    changed.clear()
    assert speech_semantics_output_schema() == schema


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"balanced": mapping()},
        {LLMModelClass.MULTIMODAL: mapping()},
        {LLMModelClass.BALANCED: object()},
    ],
)
def test_invalid_registration(value: Any) -> None:
    with pytest.raises(ValueError):
        speech_semantics_openai_role_config(value)


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        1,
        1.25,
        "文字列",
        [],
        {},
        {"members": [{"自由キー": [None, False, 7, {"nested": "値"}]}]},
        {"": "空key"},
    ],
)
def test_json_value_roundtrip(value: Any) -> None:
    payload: Any = candidate_json()
    proposition = payload["propositions"][0]
    proposition.update(value=value, claim_kind="general", execution_status=None)
    expected = deepcopy(payload)
    for item in payload["propositions"]:
        item["value"] = encode(item["value"])
    validate(payload, speech_semantics_output_schema())
    actual = decode(payload)
    assert actual == expected
    parse_candidate(actual, created_at=NOW)


@pytest.mark.parametrize(
    "case",
    ["extra", "missing", "enum", "duplicate", "degree", "execution", "budget", "bool_revision"],
)
def test_invalid_wire_or_domain_rejected_without_leak(case: str) -> None:
    payload = wire()
    if case == "extra":
        payload["private-secret-canary"] = "must-not-leak"
    elif case == "missing":
        del payload["intent_id"]
    elif case == "enum":
        payload["propositions"][0]["polarity"] = "invalid"
    elif case == "duplicate":
        payload["propositions"][0]["value"] = {
            "members": [{"key": "x", "value": 1}, {"key": "x", "value": 2}]
        }
    elif case == "degree":
        payload["propositions"][0]["degree"] = 2
    elif case == "execution":
        payload["propositions"][0]["claim_kind"] = "execution_status"
        payload["propositions"][0]["execution_status"] = None
    elif case == "budget":
        payload["question_budget"] = 1000000
    else:
        payload["revisions"]["goal_revision"] = True
    with pytest.raises(ValueError) as caught:
        decode(payload)
    assert "private-secret-canary" not in str(caught.value)
    assert "must-not-leak" not in str(caught.value)


def test_real_adapter_path_with_fake_io_preserves_payload_and_provenance() -> None:
    client = FakeClient(FakeResponse(json.dumps(wire())))
    config = speech_semantics_openai_role_config({LLMModelClass.BALANCED: mapping()})
    adapter = OpenAIResponsesAdapter(client, (config,))
    result = asyncio.run(SpeechSemanticsProviderPort(adapter, policy()).invoke(request()))
    assert validate_role_exchange(descriptor(policy()), request(), result) is None
    assert result.output is not None and result.output.schema_id == OUTPUT_SCHEMA
    assert thaw_json(result.output.value) == candidate_json()
    assert result.execution_provenance is not None
    assert result.execution_provenance.mapping_revision == 7
    assert client.calls[0]["model"] == "test-model"
    assert client.calls[0]["text"] == {
        "format": {
            "type": "json_schema",
            "name": config.provider_output_format_name,
            "strict": True,
            "schema": config.output_json_schema,
        }
    }


class Port:
    def __init__(self, result: LLMRoleResult) -> None:
        self.result = result

    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
        return self.result


@pytest.mark.parametrize("case", ["trace", "schema", "revision", "payload"])
def test_transport_and_decode_failure(case: str) -> None:
    result = replace(
        result_for(request(), wire()),
        output=StructuredPayload(PROVIDER_OUTPUT_SCHEMA, freeze_json(wire())),
    )
    if case == "trace":
        result = replace(result, trace_id="other")
    elif case == "schema":
        result = replace(result, output=StructuredPayload(OUTPUT_SCHEMA, freeze_json(wire())))
    elif case == "revision":
        result = replace(result, revisions=replace(result.revisions, source_context_revision=99))
    else:
        result = replace(
            result, output=StructuredPayload(PROVIDER_OUTPUT_SCHEMA, {"bad": "secret-canary"})
        )
    actual = asyncio.run(SpeechSemanticsProviderPort(Port(result), policy()).invoke(request()))
    assert actual.status is LLMRoleStatus.FAILED
    assert actual.failure is not None and actual.failure.code is LLMFailureCode.SCHEMA_INVALID
    assert actual.output is None and "secret-canary" not in actual.failure.message


@pytest.mark.parametrize(
    "status,code",
    [
        (LLMRoleStatus.CANCELLED, LLMFailureCode.CANCELLED),
        (LLMRoleStatus.TIMED_OUT, LLMFailureCode.TIMEOUT),
        (LLMRoleStatus.STALE, LLMFailureCode.STALE),
    ],
)
def test_non_success_unchanged(status: LLMRoleStatus, code: LLMFailureCode) -> None:
    result = replace(
        result_for(request(), candidate_json()),
        status=status,
        output=None,
        failure=LLMRoleFailure(code, "失敗"),
    )
    assert (
        asyncio.run(SpeechSemanticsProviderPort(Port(result), policy()).invoke(request())) is result
    )


def test_other_role_and_cancellation_pass_through() -> None:
    req = replace(request(), role_id="other")
    result = result_for(req, candidate_json())
    assert asyncio.run(SpeechSemanticsProviderPort(Port(result), policy()).invoke(req)) is result

    class Cancel:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(SpeechSemanticsProviderPort(Cancel(), policy()).invoke(request()))


def test_provider_descriptor_does_not_change_domain_contract() -> None:
    assert speech_semantics_provider_descriptor(policy()).output_schema_id == PROVIDER_OUTPUT_SCHEMA
    assert descriptor(policy()).output_schema_id == OUTPUT_SCHEMA
    payload = wire()
    payload["propositions"][0]["unexpected"] = 1
    with pytest.raises(ValidationError):
        validate(payload, speech_semantics_output_schema())
