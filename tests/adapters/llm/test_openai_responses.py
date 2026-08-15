import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx2
from openai import APIConnectionError, APIStatusError, APITimeoutError

from app.adapters.llm.openai_responses import (
    OpenAIResponsesAdapter,
    OpenAIResponsesModelPolicy,
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
    def __init__(self, *responses: object) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        response = self._responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def make_request(
    role_id: str = "meaning",
    *,
    input_schema_id: str = "meaning.input.v1",
    model_class: LLMModelClass = LLMModelClass.FAST,
    reasoning_effort: LLMReasoningEffort = LLMReasoningEffort.LOW,
    timeout_seconds: float = 1,
    max_attempts: int = 2,
    deadline_at: datetime | None = None,
) -> LLMRoleRequest:
    return LLMRoleRequest(
        "request-1",
        role_id,
        StructuredPayload(input_schema_id, {"message": "こんにちは"}),
        (),
        RevisionVector(1),
        (),
        LLMPriority.FOREGROUND,
        LLMInterruptibility.INTERRUPTIBLE,
        LLMStalePolicy.REJECT,
        LLMExecutionPolicy(model_class, reasoning_effort, timeout_seconds, max_attempts, 100),
        NOW,
        "trace-1",
        deadline_at,
    )


def make_config(
    *,
    role_id: str = "meaning",
    input_schema_id: str = "meaning.input.v1",
    output_schema_id: str = "meaning.output.v1",
    provider_output_format_name: str = "meaning_output_v1",
    instructions: str = "JSON objectだけを返してください。",
    model_policies: dict[LLMModelClass, OpenAIResponsesModelPolicy] | None = None,
    failure_policy: LLMFailurePolicy = LLMFailurePolicy.RETRY_BOUNDED,
) -> OpenAIResponsesRoleConfig:
    return OpenAIResponsesRoleConfig(
        role_id=role_id,
        model_policies=model_policies
        or {
            LLMModelClass.FAST: OpenAIResponsesModelPolicy(
                "provider-fast", {LLMReasoningEffort.LOW: "fast-low"}
            ),
            LLMModelClass.BALANCED: OpenAIResponsesModelPolicy(
                "provider-balanced", {LLMReasoningEffort.MEDIUM: "balanced-medium"}
            ),
            LLMModelClass.DEEP_REASONING: OpenAIResponsesModelPolicy(
                "provider-deep", {LLMReasoningEffort.HIGH: "deep-high"}
            ),
        },
        input_schema_id=input_schema_id,
        output_schema_id=output_schema_id,
        provider_output_format_name=provider_output_format_name,
        output_json_schema={
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
        },
        instructions=instructions,
        failure_policy=failure_policy,
    )


def status_error(status_code: int, message: str = "provider failure") -> APIStatusError:
    request = httpx2.Request("POST", "https://api.example.invalid/v1/responses")
    return APIStatusError(
        message,
        response=httpx2.Response(status_code, request=request),
        body=None,
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
        assert client.calls[0]["model"] == "provider-fast"
        assert client.calls[0]["reasoning"] == {"effort": "fast-low"}
        assert client.calls[0]["text"] == {
            "format": {
                "type": "json_schema",
                "name": "meaning_output_v1",
                "strict": True,
                "schema": make_config().output_json_schema,
            }
        }

    asyncio.run(scenario())


def test_unknown_role_or_schema_fails_before_provider_call() -> None:
    async def scenario() -> None:
        client = FakeClient(FakeResponse('{"ok": true}'))
        adapter = OpenAIResponsesAdapter(client, (make_config(),), now=lambda: NOW)
        for request in (make_request("unknown"), make_request(input_schema_id="wrong.input.v1")):
            result = await adapter.invoke(request)
            assert result.status is LLMRoleStatus.FAILED
            assert result.failure is not None
            assert result.failure.code is LLMFailureCode.POLICY_VIOLATION
        assert client.calls == []

    asyncio.run(scenario())


def test_role_policy_isolation_uses_the_selected_role_only() -> None:
    async def scenario() -> None:
        other = make_config(
            role_id="other",
            input_schema_id="other.input.v1",
            output_schema_id="other.output.v1",
            provider_output_format_name="other_output_v1",
            instructions="other instruction",
            model_policies={
                LLMModelClass.BALANCED: OpenAIResponsesModelPolicy(
                    "other-balanced", {LLMReasoningEffort.MEDIUM: "other-medium"}
                )
            },
        )
        client = FakeClient(FakeResponse('{"ok": true}'))
        result = await OpenAIResponsesAdapter(
            client, (make_config(), other), now=lambda: NOW
        ).invoke(
            make_request(
                "other",
                input_schema_id="other.input.v1",
                model_class=LLMModelClass.BALANCED,
                reasoning_effort=LLMReasoningEffort.MEDIUM,
            )
        )

        assert result.status is LLMRoleStatus.SUCCEEDED
        assert client.calls[0]["model"] == "other-balanced"
        assert client.calls[0]["instructions"] == "other instruction"
        assert client.calls[0]["reasoning"] == {"effort": "other-medium"}

    asyncio.run(scenario())


def test_provider_format_name_is_explicit_and_does_not_change_domain_schema_id() -> None:
    async def scenario() -> None:
        client = FakeClient(FakeResponse('{"ok": true}'))
        config = make_config(
            output_schema_id="meaning.output.v1",
            provider_output_format_name="meaning_output_v1",
        )
        result = await OpenAIResponsesAdapter(client, (config,), now=lambda: NOW).invoke(
            make_request()
        )

        assert result.status is LLMRoleStatus.SUCCEEDED
        assert result.output is not None
        assert result.output.schema_id == "meaning.output.v1"
        text = client.calls[0]["text"]
        assert isinstance(text, dict)
        format_config = text["format"]
        assert isinstance(format_config, dict)
        assert format_config["name"] == "meaning_output_v1"

    asyncio.run(scenario())


def test_invalid_provider_format_names_fail_closed_before_provider_call() -> None:
    for provider_output_format_name in ("meaning.output.v1", "a" * 65, ""):
        try:
            make_config(provider_output_format_name=provider_output_format_name)
        except ValueError:
            continue
        raise AssertionError("不正なProvider format nameが受理されました")


def test_duplicate_provider_format_names_across_roles_are_rejected() -> None:
    client = FakeClient(FakeResponse('{"ok": true}'))
    other = make_config(
        role_id="other",
        input_schema_id="other.input.v1",
        output_schema_id="other.output.v1",
        provider_output_format_name="meaning_output_v1",
    )

    try:
        OpenAIResponsesAdapter(client, (make_config(), other), now=lambda: NOW)
    except ValueError:
        pass
    else:
        raise AssertionError("Role間で重複するProvider format nameが受理されました")


def test_fast_balanced_and_deep_model_policy_mappings_are_explicit() -> None:
    async def scenario() -> None:
        for model_class, effort, expected_model, expected_effort in (
            (LLMModelClass.FAST, LLMReasoningEffort.LOW, "provider-fast", "fast-low"),
            (
                LLMModelClass.BALANCED,
                LLMReasoningEffort.MEDIUM,
                "provider-balanced",
                "balanced-medium",
            ),
            (
                LLMModelClass.DEEP_REASONING,
                LLMReasoningEffort.HIGH,
                "provider-deep",
                "deep-high",
            ),
        ):
            client = FakeClient(FakeResponse('{"ok": true}'))
            result = await OpenAIResponsesAdapter(
                client, (make_config(),), now=lambda: NOW
            ).invoke(make_request(model_class=model_class, reasoning_effort=effort))
            assert result.status is LLMRoleStatus.SUCCEEDED
            assert client.calls[0]["model"] == expected_model
            assert client.calls[0]["reasoning"] == {"effort": expected_effort}

    asyncio.run(scenario())


def test_unsupported_model_or_reasoning_mapping_fails_closed_before_provider_call() -> None:
    async def scenario() -> None:
        client = FakeClient(FakeResponse('{"ok": true}'))
        adapter = OpenAIResponsesAdapter(client, (make_config(),), now=lambda: NOW)
        for request in (
            make_request(model_class=LLMModelClass.MULTIMODAL),
            make_request(reasoning_effort=LLMReasoningEffort.HIGH),
        ):
            result = await adapter.invoke(request)
            assert result.status is LLMRoleStatus.FAILED
            assert result.failure is not None
            assert result.failure.code is LLMFailureCode.POLICY_VIOLATION
        assert client.calls == []

    asyncio.run(scenario())


def test_malformed_provider_output_and_schema_violation_are_schema_failures() -> None:
    async def scenario() -> None:
        for output_text in ("[]", "{}"):
            result = await OpenAIResponsesAdapter(
                FakeClient(FakeResponse(output_text)), (make_config(),), now=lambda: NOW
            ).invoke(make_request())
            assert result.status is LLMRoleStatus.FAILED
            assert result.failure is not None
            assert result.failure.code is LLMFailureCode.SCHEMA_INVALID

    asyncio.run(scenario())


def test_retryable_transport_and_rate_limit_errors_retry_with_bounded_policy() -> None:
    async def scenario() -> None:
        request = httpx2.Request("POST", "https://api.example.invalid/v1/responses")
        transport = APIConnectionError(
            request=request
        )
        for error in (
            transport,
            APITimeoutError(request),
            status_error(408),
            status_error(429),
            status_error(500),
        ):
            client = FakeClient(error, FakeResponse('{"ok": true}'))
            result = await OpenAIResponsesAdapter(client, (make_config(),), now=lambda: NOW).invoke(
                make_request()
            )
            assert result.status is LLMRoleStatus.SUCCEEDED
            assert result.attempt_count == 2
            assert len(client.calls) == 2

    asyncio.run(scenario())


def test_permanent_provider_errors_do_not_retry_and_do_not_claim_retryable() -> None:
    async def scenario() -> None:
        for status_code in (401, 403, 400):
            client = FakeClient(status_error(status_code, "credential-or-prompt-secret"))
            result = await OpenAIResponsesAdapter(client, (make_config(),), now=lambda: NOW).invoke(
                make_request(max_attempts=3)
            )
            assert result.status is LLMRoleStatus.FAILED
            assert result.failure is not None
            assert result.failure.code is LLMFailureCode.PROVIDER_ERROR
            assert not result.failure.retryable
            assert result.attempt_count == 1
            assert len(client.calls) == 1

    asyncio.run(scenario())


def test_retry_stops_at_max_attempts_and_reports_the_classified_retryability() -> None:
    async def scenario() -> None:
        client = FakeClient(status_error(429), status_error(429), status_error(429))
        result = await OpenAIResponsesAdapter(client, (make_config(),), now=lambda: NOW).invoke(
            make_request(max_attempts=3)
        )

        assert result.status is LLMRoleStatus.FAILED
        assert result.failure is not None
        assert result.failure.code is LLMFailureCode.PROVIDER_UNAVAILABLE
        assert result.failure.retryable
        assert result.attempt_count == 3
        assert len(client.calls) == 3

    asyncio.run(scenario())


def test_retryable_failure_does_not_retry_without_retry_bounded_policy() -> None:
    async def scenario() -> None:
        client = FakeClient(status_error(429), FakeResponse('{"ok": true}'))
        result = await OpenAIResponsesAdapter(
            client,
            (make_config(failure_policy=LLMFailurePolicy.FAIL_CLOSED),),
            now=lambda: NOW,
        ).invoke(make_request(max_attempts=2))

        assert result.status is LLMRoleStatus.FAILED
        assert result.failure is not None
        assert result.failure.retryable
        assert result.attempt_count == 1
        assert len(client.calls) == 1

    asyncio.run(scenario())


def test_timeout_and_cancellation_return_non_committable_typed_results() -> None:
    class SlowClient:
        def __init__(self) -> None:
            self.started = asyncio.Event()

        async def create(self, **kwargs: object) -> object:
            self.started.set()
            await asyncio.Event().wait()
            raise AssertionError("到達不能")

    async def scenario() -> None:
        timeout_result = await OpenAIResponsesAdapter(
            SlowClient(), (make_config(),), now=lambda: NOW
        ).invoke(make_request(timeout_seconds=0.001))
        assert timeout_result.status is LLMRoleStatus.TIMED_OUT

        client = SlowClient()
        task = asyncio.create_task(
            OpenAIResponsesAdapter(client, (make_config(),), now=lambda: NOW).invoke(make_request())
        )
        await client.started.wait()
        task.cancel()
        cancelled_result = await task
        assert cancelled_result.status is LLMRoleStatus.CANCELLED

    asyncio.run(scenario())


def test_expired_deadline_prevents_provider_call_and_stops_a_retry() -> None:
    class Clock:
        value = NOW

        def now(self) -> datetime:
            return self.value

    class ExpiringClient(FakeClient):
        def __init__(self, clock: Clock) -> None:
            super().__init__(status_error(429))
            self._clock = clock

        async def create(self, **kwargs: object) -> object:
            self._clock.value = NOW + timedelta(seconds=2)
            return await super().create(**kwargs)

    async def scenario() -> None:
        expired_client = FakeClient(FakeResponse('{"ok": true}'))
        expired = await OpenAIResponsesAdapter(
            expired_client, (make_config(),), now=lambda: NOW + timedelta(seconds=2)
        ).invoke(make_request(deadline_at=NOW + timedelta(seconds=1)))
        assert expired.status is LLMRoleStatus.TIMED_OUT
        assert expired_client.calls == []

        clock = Clock()
        client = ExpiringClient(clock)
        retried = await OpenAIResponsesAdapter(client, (make_config(),), now=clock.now).invoke(
            make_request(deadline_at=NOW + timedelta(seconds=1), max_attempts=3)
        )
        assert retried.status is LLMRoleStatus.TIMED_OUT
        assert retried.attempt_count == 1
        assert len(client.calls) == 1

    asyncio.run(scenario())


def test_failure_does_not_expose_provider_message_prompt_or_api_key() -> None:
    async def scenario() -> None:
        api_key = "sk-test-secret"
        prompt = "private prompt"
        client = FakeClient(status_error(401, f"{api_key} {prompt}"))
        config = make_config(instructions=prompt)
        result = await OpenAIResponsesAdapter(client, (config,), now=lambda: NOW).invoke(
            make_request()
        )

        assert result.failure is not None
        rendered = str(result.failure.to_dict())
        assert api_key not in rendered
        assert prompt not in rendered
        assert "provider failure" not in rendered

    asyncio.run(scenario())
