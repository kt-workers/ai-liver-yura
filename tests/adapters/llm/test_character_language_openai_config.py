import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from app.adapters.llm.character_language import (
    CHARACTER_LANGUAGE_PROVIDER_FORMAT_NAME,
    character_language_openai_role_config,
    character_language_openai_role_configs,
)
from app.adapters.llm.openai_responses import OpenAIResponsesAdapter
from app.domain.character_language import (
    character_language_instructions,
    character_language_output_schema,
)
from app.domain.character_language.realizer import INPUT_SCHEMA, OUTPUT_SCHEMA, ROLE_ID
from app.domain.contracts import RevisionVector
from app.domain.llm import (
    LLMFailureCode,
    LLMInterruptibility,
    LLMModelClass,
    LLMPriority,
    LLMReasoningEffort,
    LLMRoleRequest,
    LLMRoleStatus,
    LLMStalePolicy,
    StructuredPayload,
)
from tests.helpers.llm import make_execution_policy

NOW = datetime(2026, 8, 19, tzinfo=timezone.utc)
REASONING_BY_EFFORT = {effort: effort.value for effort in LLMReasoningEffort}


@dataclass
class FakeUsage:
    input_tokens: int = 10
    output_tokens: int = 20


@dataclass
class FakeResponse:
    output_text: str
    usage: FakeUsage = field(default_factory=FakeUsage)


class FakeClient:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return self.response


def _request(
    *,
    model_class: LLMModelClass = LLMModelClass.BALANCED,
    reasoning_effort: LLMReasoningEffort = LLMReasoningEffort.MEDIUM,
) -> LLMRoleRequest:
    return LLMRoleRequest(
        "request-1",
        ROLE_ID,
        StructuredPayload(INPUT_SCHEMA, {"fixture": True}),
        ("event-1",),
        RevisionVector(1),
        (),
        LLMPriority.FOREGROUND,
        LLMInterruptibility.INTERRUPTIBLE,
        LLMStalePolicy.REJECT,
        make_execution_policy(model_class, reasoning_effort, 5, 1, 1000),
        NOW,
        "trace-1",
    )


def _candidate_payload() -> dict[str, object]:
    return {
        "candidate_id": "candidate-1",
        "request_id": "request-1",
        "semantic_plan_id": "plan-1",
        "source_decision_id": "decision-1",
        "source_intent_id": "intent-1",
        "source_event_ids": ["event-1"],
        "revisions": {
            "source_context_revision": 1,
            "goal_revision": None,
            "attention_revision": None,
        },
        "character_id": "yura",
        "character_schema_version": 1,
        "character_definition_revision": 1,
        "segments": [
            {
                "segment_id": "s1",
                "text": "ありがと。",
                "realization_refs": ["p1"],
                "boundary_after": "sentence",
                "emphasis": "neutral",
                "hesitation": "none",
            }
        ],
        "question_budget_used": 0,
        "new_direction_budget_used": 0,
    }


def test_production_config_owns_role_schema_format_and_explicit_reasoning_mapping() -> None:
    config = character_language_openai_role_config(
        {
            LLMModelClass.FAST: "model-fast",
            LLMModelClass.BALANCED: "model-balanced",
            LLMModelClass.DEEP_REASONING: "model-deep",
        },
        reasoning_by_effort=REASONING_BY_EFFORT,
    )

    assert config.role_id == ROLE_ID
    assert config.input_schema_id == INPUT_SCHEMA
    assert config.output_schema_id == OUTPUT_SCHEMA
    assert config.provider_output_format_name == CHARACTER_LANGUAGE_PROVIDER_FORMAT_NAME
    assert config.output_json_schema == character_language_output_schema()
    assert config.instructions == character_language_instructions()
    assert config.model_policies[LLMModelClass.FAST].model == "model-fast"
    assert config.model_policies[LLMModelClass.BALANCED].model == "model-balanced"
    assert config.model_policies[LLMModelClass.DEEP_REASONING].model == "model-deep"
    actual_reasoning = dict(
        config.model_policies[LLMModelClass.BALANCED].reasoning_by_effort
    )
    assert actual_reasoning == REASONING_BY_EFFORT
    assert character_language_openai_role_configs(
        {LLMModelClass.BALANCED: "model-balanced"},
        reasoning_by_effort=REASONING_BY_EFFORT,
    ) == (
        character_language_openai_role_config(
            {LLMModelClass.BALANCED: "model-balanced"},
            reasoning_by_effort=REASONING_BY_EFFORT,
        ),
    )


def test_custom_reasoning_mapping_is_explicit_and_preserved() -> None:
    config = character_language_openai_role_config(
        {LLMModelClass.BALANCED: "model-balanced"},
        reasoning_by_effort={LLMReasoningEffort.MEDIUM: "provider-medium"},
    )
    assert dict(config.model_policies[LLMModelClass.BALANCED].reasoning_by_effort) == {
        LLMReasoningEffort.MEDIUM: "provider-medium"
    }


@pytest.mark.parametrize(
    "models",
    [
        {},
        {LLMModelClass.MULTIMODAL: "vision-model"},
        {LLMModelClass.BALANCED: ""},
    ],
)
def test_invalid_or_multimodal_model_mapping_is_rejected(
    models: dict[LLMModelClass, str],
) -> None:
    with pytest.raises(ValueError, match="model mapping"):
        character_language_openai_role_config(
            models,
            reasoning_by_effort=REASONING_BY_EFFORT,
        )


@pytest.mark.parametrize(
    "reasoning",
    [
        {},
        {LLMReasoningEffort.MEDIUM: ""},
    ],
)
def test_invalid_reasoning_mapping_is_rejected(
    reasoning: dict[LLMReasoningEffort, str],
) -> None:
    with pytest.raises(ValueError, match="reasoning mapping"):
        character_language_openai_role_config(
            {LLMModelClass.BALANCED: "model-balanced"},
            reasoning_by_effort=reasoning,
        )


def test_missing_model_or_reasoning_mapping_fails_before_provider_call() -> None:
    async def scenario() -> None:
        client = FakeClient(FakeResponse(json.dumps(_candidate_payload())))
        config = character_language_openai_role_config(
            {LLMModelClass.BALANCED: "model-balanced"},
            reasoning_by_effort={LLMReasoningEffort.MEDIUM: "provider-medium"},
        )
        adapter = OpenAIResponsesAdapter(client, (config,), now=lambda: NOW)

        for request in (
            _request(model_class=LLMModelClass.FAST),
            _request(reasoning_effort=LLMReasoningEffort.HIGH),
        ):
            result = await adapter.invoke(request)
            assert result.status is LLMRoleStatus.FAILED
            assert result.failure is not None
            assert result.failure.code is LLMFailureCode.POLICY_VIOLATION
        assert client.calls == []

    asyncio.run(scenario())


def test_valid_provider_call_uses_production_instructions_schema_format_and_mapping() -> None:
    async def scenario() -> None:
        client = FakeClient(FakeResponse(json.dumps(_candidate_payload(), ensure_ascii=False)))
        config = character_language_openai_role_config(
            {LLMModelClass.BALANCED: "model-balanced"},
            reasoning_by_effort={LLMReasoningEffort.MEDIUM: "provider-medium"},
        )
        result = await OpenAIResponsesAdapter(client, (config,), now=lambda: NOW).invoke(_request())

        assert result.status is LLMRoleStatus.SUCCEEDED
        assert result.output is not None
        assert result.output.schema_id == OUTPUT_SCHEMA
        assert len(client.calls) == 1
        call = client.calls[0]
        assert call["model"] == "model-balanced"
        assert call["reasoning"] == {"effort": "provider-medium"}
        assert call["instructions"] == character_language_instructions()
        assert call["text"] == {
            "format": {
                "type": "json_schema",
                "name": CHARACTER_LANGUAGE_PROVIDER_FORMAT_NAME,
                "strict": True,
                "schema": character_language_output_schema(),
            }
        }

    asyncio.run(scenario())


def test_schema_violation_fails_closed_without_character_fallback() -> None:
    async def scenario() -> None:
        invalid = _candidate_payload()
        invalid["unexpected_semantic_override"] = "invented"
        client = FakeClient(FakeResponse(json.dumps(invalid, ensure_ascii=False)))
        config = character_language_openai_role_config(
            {LLMModelClass.BALANCED: "model-balanced"},
            reasoning_by_effort=REASONING_BY_EFFORT,
        )
        result = await OpenAIResponsesAdapter(client, (config,), now=lambda: NOW).invoke(_request())

        assert result.status is LLMRoleStatus.FAILED
        assert result.failure is not None
        assert result.failure.code is LLMFailureCode.SCHEMA_INVALID
        assert result.output is None

    asyncio.run(scenario())
