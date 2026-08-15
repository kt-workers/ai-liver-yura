import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.adapters.llm.openai_responses import (
    OpenAIResponsesAdapter,
    OpenAIResponsesRoleConfig,
)
from app.domain.contracts import RevisionVector
from app.domain.llm import (
    LLMExecutionPolicy,
    LLMFailureCode,
    LLMFailurePolicy,
    LLMInterruptibility,
    LLMModelClass,
    LLMPriority,
    LLMReasoningEffort,
    LLMRoleRequest,
    LLMRoleStatus,
    LLMStalePolicy,
    StructuredPayload,
)

NOW = datetime(2026, 8, 15, tzinfo=timezone.utc)


@dataclass
class FakeUsage:
    input_tokens: int = 2
    output_tokens: int = 3


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
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


def make_request(role_id: str = "meaning") -> LLMRoleRequest:
    return LLMRoleRequest(
        "request-1",
        role_id,
        StructuredPayload("meaning.input.v1", {"message": "こんにちは"}),
        (),
        RevisionVector(1),
        (),
        LLMPriority.FOREGROUND,
        LLMInterruptibility.INTERRUPTIBLE,
        LLMStalePolicy.REJECT,
        LLMExecutionPolicy(LLMModelClass.FAST, LLMReasoningEffort.LOW, 1, 2, 100),
        NOW,
        "trace-1",
    )


def make_config() -> OpenAIResponsesRoleConfig:
    return OpenAIResponsesRoleConfig(
        "meaning",
        "gpt-5-mini",
        "meaning.input.v1",
        "meaning.output.v1",
        {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
        "JSON objectだけを返してください。",
        LLMFailurePolicy.RETRY_BOUNDED,
    )


def test_success_uses_strict_json_schema_and_typed_result() -> None:
    async def scenario() -> None:
        client = FakeClient(FakeResponse('{"ok": true}'))
        result = await OpenAIResponsesAdapter(client, (make_config(),), now=lambda: NOW).invoke(
            make_request()
        )

        assert result.status is LLMRoleStatus.SUCCEEDED
        assert result.output is not None
        assert result.output.schema_id == "meaning.output.v1"
        assert result.token_usage.input_tokens == 2
        assert client.calls[0]["text"] == {
            "format": {
                "type": "json_schema",
                "name": "meaning.output.v1",
                "strict": True,
                "schema": make_config().output_json_schema,
            }
        }

    asyncio.run(scenario())


def test_unknown_role_fails_before_provider_call() -> None:
    async def scenario() -> None:
        client = FakeClient(FakeResponse('{"ok": true}'))
        result = await OpenAIResponsesAdapter(client, (make_config(),), now=lambda: NOW).invoke(
            make_request("unknown")
        )

        assert result.status is LLMRoleStatus.FAILED
        assert result.failure is not None
        assert result.failure.code is LLMFailureCode.POLICY_VIOLATION
        assert client.calls == []

    asyncio.run(scenario())


def test_malformed_provider_output_is_schema_failure() -> None:
    async def scenario() -> None:
        result = await OpenAIResponsesAdapter(
            FakeClient(FakeResponse("[]")), (make_config(),), now=lambda: NOW
        ).invoke(make_request())

        assert result.status is LLMRoleStatus.FAILED
        assert result.failure is not None
        assert result.failure.code is LLMFailureCode.SCHEMA_INVALID

    asyncio.run(scenario())


def test_json_object_that_breaks_output_schema_is_schema_failure() -> None:
    async def scenario() -> None:
        result = await OpenAIResponsesAdapter(
            FakeClient(FakeResponse("{}")), (make_config(),), now=lambda: NOW
        ).invoke(make_request())

        assert result.status is LLMRoleStatus.FAILED
        assert result.failure is not None
        assert result.failure.code is LLMFailureCode.SCHEMA_INVALID

    asyncio.run(scenario())


def test_provider_error_retries_only_with_bounded_retry_policy() -> None:
    async def scenario() -> None:
        client = FakeClient(RuntimeError("transport failed"))
        result = await OpenAIResponsesAdapter(client, (make_config(),), now=lambda: NOW).invoke(
            make_request()
        )

        assert result.status is LLMRoleStatus.FAILED
        assert result.attempt_count == 2
        assert len(client.calls) == 2
        assert result.failure is not None
        assert result.failure.retryable

    asyncio.run(scenario())
