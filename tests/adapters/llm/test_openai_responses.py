import asyncio
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone

import httpx2
import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError

from app.adapters.llm.openai_responses import (
    OpenAIResponsesAdapter,
    OpenAIResponsesModelPolicy,
    OpenAIResponsesRoleConfig,
    OpenAIResponsesTemperatureMapping,
)
from app.adapters.llm.operational_diagnostics import (
    LLMProviderOperationalDiagnostic,
    LLMProviderOperationalDiagnosticPublicationPolicy,
    LLMProviderOperationalFailureCategory,
    LLMProviderSanitizedDetailCode,
)
from app.domain.contracts import RevisionVector
from app.domain.llm import (
    LLMFailureCode,
    LLMFailurePolicy,
    LLMInterruptibility,
    LLMModelClass,
    LLMPriority,
    LLMReasoningEffort,
    LLMRequestRetryPolicy,
    LLMRoleRequest,
    LLMRoleStatus,
    LLMStalePolicy,
    StructuredPayload,
)
from tests.helpers.llm import make_execution_policy

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
    max_output_tokens: int = 100,
    temperature_normalized: float | None = None,
    retry_policy: LLMRequestRetryPolicy | None = None,
    deadline_at: datetime | None = None,
) -> LLMRoleRequest:
    execution_policy = make_execution_policy(
        model_class,
        reasoning_effort,
        timeout_seconds,
        max_attempts,
        max_output_tokens,
        temperature_normalized,
    )
    if retry_policy is not None:
        execution_policy = replace(execution_policy, retry_policy=retry_policy)
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
        execution_policy,
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
                "meaning.openai.fast", 1, "provider-fast", {LLMReasoningEffort.LOW: "fast-low"}
            ),
            LLMModelClass.BALANCED: OpenAIResponsesModelPolicy(
                "meaning.openai.balanced",
                1,
                "provider-balanced",
                {LLMReasoningEffort.MEDIUM: "balanced-medium"},
            ),
            LLMModelClass.DEEP_REASONING: OpenAIResponsesModelPolicy(
                "meaning.openai.deep", 1, "provider-deep", {LLMReasoningEffort.HIGH: "deep-high"}
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


def status_error(
    status_code: int,
    message: str = "provider failure",
    *,
    provider_code: str | None = None,
    provider_request_id: str | None = None,
) -> APIStatusError:
    request = httpx2.Request("POST", "https://api.example.invalid/v1/responses")
    headers = {} if provider_request_id is None else {"x-request-id": provider_request_id}
    error = APIStatusError(
        message,
        response=httpx2.Response(status_code, request=request, headers=headers),
        body=None,
    )
    if provider_code is not None:
        error.code = provider_code
    return error


@dataclass
class DiagnosticSink:
    diagnostics: list[LLMProviderOperationalDiagnostic] = field(default_factory=list)
    should_fail: bool = False

    def publish(self, diagnostic: LLMProviderOperationalDiagnostic) -> None:
        if self.should_fail:
            raise RuntimeError("diagnostic-sink-secret")
        self.diagnostics.append(diagnostic)


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
                    "other.openai.balanced",
                    1,
                    "other-balanced",
                    {LLMReasoningEffort.MEDIUM: "other-medium"},
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
            result = await OpenAIResponsesAdapter(client, (make_config(),), now=lambda: NOW).invoke(
                make_request(model_class=model_class, reasoning_effort=effort)
            )
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


def test_retryable_transport_timeout_and_classified_rate_limit_retry_with_bounded_policy() -> None:
    async def scenario() -> None:
        request = httpx2.Request("POST", "https://api.example.invalid/v1/responses")
        transport = APIConnectionError(request=request)
        for error in (
            transport,
            APITimeoutError(request),
            status_error(408),
            status_error(429, provider_code="rate_limit_exceeded"),
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


def test_classified_transient_retry_stops_at_max_attempts_without_claiming_further_retry() -> None:
    async def scenario() -> None:
        client = FakeClient(
            status_error(429, provider_code="rate_limit_exceeded"),
            status_error(429, provider_code="rate_limit_exceeded"),
            status_error(429, provider_code="rate_limit_exceeded"),
        )
        result = await OpenAIResponsesAdapter(client, (make_config(),), now=lambda: NOW).invoke(
            make_request(max_attempts=3)
        )

        assert result.status is LLMRoleStatus.FAILED
        assert result.failure is not None
        assert result.failure.code is LLMFailureCode.PROVIDER_UNAVAILABLE
        assert not result.failure.retryable
        assert result.attempt_count == 3
        assert len(client.calls) == 3

    asyncio.run(scenario())


def test_transient_failure_does_not_retry_without_retry_bounded_policy() -> None:
    async def scenario() -> None:
        client = FakeClient(
            status_error(429, provider_code="rate_limit_exceeded"), FakeResponse('{"ok": true}')
        )
        result = await OpenAIResponsesAdapter(
            client,
            (make_config(failure_policy=LLMFailurePolicy.FAIL_CLOSED),),
            now=lambda: NOW,
        ).invoke(make_request(max_attempts=2))

        assert result.status is LLMRoleStatus.FAILED
        assert result.failure is not None
        assert not result.failure.retryable
        assert result.attempt_count == 1
        assert len(client.calls) == 1

    asyncio.run(scenario())


def test_d10_mapping_resolves_temperature_enforces_token_limit_and_keeps_provenance() -> None:
    async def scenario() -> None:
        mapping = OpenAIResponsesModelPolicy(
            "meaning.openai.fast.v2",
            2,
            "provider-fast",
            {LLMReasoningEffort.LOW: "fast-low"},
            OpenAIResponsesTemperatureMapping(0.2, 1.4),
            120,
        )
        config = make_config(model_policies={LLMModelClass.FAST: mapping})
        client = FakeClient(
            FakeResponse('{"ok": true}'),
            FakeResponse('{"ok": true}'),
            FakeResponse('{"ok": true}'),
            FakeResponse('{"ok": true}'),
        )
        adapter = OpenAIResponsesAdapter(client, (config,), now=lambda: NOW)
        for normalized in (0.0, 0.5, 1.0):
            result = await adapter.invoke(
                make_request(temperature_normalized=normalized, max_output_tokens=120)
            )
            assert result.status is LLMRoleStatus.SUCCEEDED
            assert result.execution_provenance is not None
            assert result.execution_provenance.to_dict() == {
                "policy_id": "test.llm.execution",
                "policy_revision": 1,
                "mapping_id": "meaning.openai.fast.v2",
                "mapping_revision": 2,
            }
        assert [call["temperature"] for call in client.calls[:3]] == [0.2, 0.8, 1.4]

        no_temperature = await adapter.invoke(make_request(max_output_tokens=120))
        assert no_temperature.status is LLMRoleStatus.SUCCEEDED
        assert "temperature" not in client.calls[3]

        token_limit = await adapter.invoke(make_request(max_output_tokens=121))
        assert token_limit.failure is not None
        assert token_limit.failure.code is LLMFailureCode.POLICY_VIOLATION
        assert len(client.calls) == 4

        unsupported_client = FakeClient(FakeResponse('{"ok": true}'))
        unsupported = await OpenAIResponsesAdapter(
            unsupported_client,
            (make_config(),),
            now=lambda: NOW,
        ).invoke(make_request(temperature_normalized=0.4))
        assert unsupported.failure is not None
        assert unsupported.failure.code is LLMFailureCode.POLICY_VIOLATION
        assert unsupported_client.calls == []

    asyncio.run(scenario())


def test_d10_retry_uses_deterministic_backoff_and_rechecks_deadline_and_shutdown() -> None:
    async def scenario() -> None:
        delays: list[float] = []

        async def record_sleep(delay: float) -> None:
            delays.append(delay)

        retry_policy = LLMRequestRetryPolicy(1, 2, 3)
        client = FakeClient(
            APIConnectionError(
                request=httpx2.Request("POST", "https://api.example.invalid/v1/responses")
            ),
            APIConnectionError(
                request=httpx2.Request("POST", "https://api.example.invalid/v1/responses")
            ),
            FakeResponse('{"ok": true}'),
        )
        result = await OpenAIResponsesAdapter(
            client,
            (make_config(),),
            now=lambda: NOW,
            sleep=record_sleep,
        ).invoke(make_request(max_attempts=3, retry_policy=retry_policy))
        assert result.status is LLMRoleStatus.SUCCEEDED
        assert delays == [1.0, 2.0]
        assert len(client.calls) == 3

        class Clock:
            def __init__(self) -> None:
                self.value = NOW

            def now(self) -> datetime:
                return self.value

        clock = Clock()

        async def elapse_past_deadline(delay: float) -> None:
            clock.value += timedelta(seconds=delay)

        expired_client = FakeClient(
            APIConnectionError(
                request=httpx2.Request("POST", "https://api.example.invalid/v1/responses")
            ),
            FakeResponse('{"ok": true}'),
        )
        expired = await OpenAIResponsesAdapter(
            expired_client,
            (make_config(),),
            now=clock.now,
            sleep=elapse_past_deadline,
        ).invoke(
            make_request(
                max_attempts=2,
                retry_policy=LLMRequestRetryPolicy(2, 1, 2),
                deadline_at=NOW + timedelta(seconds=1),
            )
        )
        assert expired.status is LLMRoleStatus.TIMED_OUT
        assert len(expired_client.calls) == 1

        shutdown = {"requested": False}

        async def request_shutdown(_: float) -> None:
            shutdown["requested"] = True

        shutdown_client = FakeClient(
            APIConnectionError(
                request=httpx2.Request("POST", "https://api.example.invalid/v1/responses")
            ),
            FakeResponse('{"ok": true}'),
        )
        cancelled = await OpenAIResponsesAdapter(
            shutdown_client,
            (make_config(),),
            now=lambda: NOW,
            is_shutdown=lambda: shutdown["requested"],
            sleep=request_shutdown,
        ).invoke(make_request(max_attempts=2, retry_policy=retry_policy))
        assert cancelled.status is LLMRoleStatus.CANCELLED
        assert len(shutdown_client.calls) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "provider_min,provider_max",
    [(True, 1.0), (0.0, float("nan")), (2.0, 1.0)],
)
def test_temperature_mapping_rejects_invalid_provider_numeric_values(
    provider_min: object, provider_max: object
) -> None:
    with pytest.raises(ValueError):
        OpenAIResponsesTemperatureMapping(provider_min, provider_max)  # type: ignore[arg-type]


def test_timeout_and_cancellation_return_non_committable_typed_results() -> None:
    class SlowClient:
        def __init__(self) -> None:
            self.started = asyncio.Event()

        async def create(self, **kwargs: object) -> object:
            self.started.set()
            await asyncio.Event().wait()
            raise AssertionError("到達不能")

    async def scenario() -> None:
        class TimeoutThenSuccess:
            def __init__(self) -> None:
                self.calls = 0

            async def create(self, **kwargs: object) -> object:
                self.calls += 1
                if self.calls == 1:
                    await asyncio.sleep(0.01)
                return FakeResponse('{"ok": true}')

        sink = DiagnosticSink()
        timeout_result = await OpenAIResponsesAdapter(
            TimeoutThenSuccess(), (make_config(),), now=lambda: NOW, diagnostic_sink=sink
        ).invoke(make_request(timeout_seconds=0.001))
        assert timeout_result.status is LLMRoleStatus.SUCCEEDED
        assert timeout_result.attempt_count == 2
        assert (
            sink.diagnostics[-1].category is LLMProviderOperationalFailureCategory.REQUEST_TIMEOUT
        )

        client = SlowClient()
        cancel_sink = DiagnosticSink()
        task = asyncio.create_task(
            OpenAIResponsesAdapter(
                client, (make_config(),), now=lambda: NOW, diagnostic_sink=cancel_sink
            ).invoke(make_request())
        )
        await client.started.wait()
        task.cancel()
        cancelled_result = await task
        assert cancelled_result.status is LLMRoleStatus.CANCELLED
        assert (
            cancel_sink.diagnostics[-1].category is LLMProviderOperationalFailureCategory.CANCELLED
        )

    asyncio.run(scenario())


def test_expired_deadline_prevents_provider_call_and_stops_a_retry() -> None:
    class Clock:
        value = NOW

        def now(self) -> datetime:
            return self.value

    class ExpiringClient(FakeClient):
        def __init__(self, clock: Clock) -> None:
            super().__init__(status_error(429, provider_code="rate_limit_exceeded"))
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


def test_operational_diagnostics_classify_safe_provider_causes_and_request_id() -> None:
    async def scenario() -> None:
        cases = (
            (
                APIConnectionError(
                    request=httpx2.Request("POST", "https://api.example.invalid/v1/responses")
                ),
                LLMProviderOperationalFailureCategory.TRANSPORT_UNAVAILABLE,
                None,
                LLMProviderSanitizedDetailCode.SDK_CONNECTION,
            ),
            (
                APITimeoutError(httpx2.Request("POST", "https://api.example.invalid/v1/responses")),
                LLMProviderOperationalFailureCategory.REQUEST_TIMEOUT,
                None,
                LLMProviderSanitizedDetailCode.SDK_TIMEOUT,
            ),
            (
                status_error(408),
                LLMProviderOperationalFailureCategory.REQUEST_TIMEOUT,
                408,
                LLMProviderSanitizedDetailCode.HTTP_408,
            ),
            (
                status_error(
                    429,
                    provider_code="rate_limit_exceeded",
                    provider_request_id="req-safe-1",
                ),
                LLMProviderOperationalFailureCategory.RATE_LIMITED_TRANSIENT,
                429,
                LLMProviderSanitizedDetailCode.HTTP_429_TRANSIENT,
            ),
            (
                status_error(503),
                LLMProviderOperationalFailureCategory.PROVIDER_SERVER_ERROR,
                503,
                LLMProviderSanitizedDetailCode.HTTP_5XX,
            ),
            (
                status_error(401),
                LLMProviderOperationalFailureCategory.AUTHENTICATION_OR_PERMISSION_FAILED,
                401,
                LLMProviderSanitizedDetailCode.HTTP_AUTHENTICATION,
            ),
            (
                status_error(400),
                LLMProviderOperationalFailureCategory.PROVIDER_REQUEST_REJECTED,
                400,
                LLMProviderSanitizedDetailCode.HTTP_REQUEST_REJECTED,
            ),
        )
        for error, category, status, detail in cases:
            sink = DiagnosticSink()
            result = await OpenAIResponsesAdapter(
                FakeClient(error), (make_config(),), now=lambda: NOW, diagnostic_sink=sink
            ).invoke(make_request(max_attempts=1))
            assert result.failure is not None
            assert len(sink.diagnostics) == 1
            diagnostic = sink.diagnostics[0]
            assert diagnostic.category is category
            assert diagnostic.http_status == status
            assert diagnostic.sanitized_detail_code is detail
        assert sink.diagnostics[0].provider_request_id is None

        request_id_sink = DiagnosticSink()
        await OpenAIResponsesAdapter(
            FakeClient(
                status_error(
                    429,
                    provider_code="rate_limit_exceeded",
                    provider_request_id="req-safe-1",
                )
            ),
            (make_config(),),
            now=lambda: NOW,
            diagnostic_sink=request_id_sink,
        ).invoke(make_request(max_attempts=1))
        assert request_id_sink.diagnostics[0].provider_request_id == "req-safe-1"

    asyncio.run(scenario())


def test_quota_and_unclassified_rate_limit_fail_closed_without_immediate_retry() -> None:
    async def scenario() -> None:
        for provider_code, category, detail in (
            (
                "insufficient_quota",
                LLMProviderOperationalFailureCategory.QUOTA_OR_BILLING_EXHAUSTED,
                LLMProviderSanitizedDetailCode.HTTP_429_QUOTA_OR_BILLING,
            ),
            (
                None,
                LLMProviderOperationalFailureCategory.UNKNOWN_PROVIDER_FAILURE,
                LLMProviderSanitizedDetailCode.HTTP_429_UNCLASSIFIED,
            ),
        ):
            sink = DiagnosticSink()
            client = FakeClient(
                status_error(429, provider_code=provider_code), FakeResponse('{"ok": true}')
            )
            result = await OpenAIResponsesAdapter(
                client, (make_config(),), now=lambda: NOW, diagnostic_sink=sink
            ).invoke(make_request(max_attempts=2))
            assert result.failure is not None
            assert not result.failure.retryable
            assert len(client.calls) == 1
            assert sink.diagnostics[0].category is category
            assert sink.diagnostics[0].sanitized_detail_code is detail
            assert not sink.diagnostics[0].retryable

    asyncio.run(scenario())


def test_provider_envelope_anomaly_is_protocol_error_not_schema_error() -> None:
    async def scenario() -> None:
        sink = DiagnosticSink()
        result = await OpenAIResponsesAdapter(
            FakeClient(object()), (make_config(),), now=lambda: NOW, diagnostic_sink=sink
        ).invoke(make_request(max_attempts=1))
        assert result.failure is not None
        assert result.failure.code is LLMFailureCode.PROVIDER_ERROR
        assert (
            sink.diagnostics[0].category
            is LLMProviderOperationalFailureCategory.PROVIDER_PROTOCOL_ERROR
        )
        malformed = await OpenAIResponsesAdapter(
            FakeClient(FakeResponse("not-json")), (make_config(),), now=lambda: NOW
        ).invoke(make_request(max_attempts=1))
        assert malformed.failure is not None
        assert malformed.failure.code is LLMFailureCode.SCHEMA_INVALID

    asyncio.run(scenario())


def test_actual_provider_cause_diagnostic_survives_shutdown_and_deadline() -> None:
    class Clock:
        value = NOW

        def now(self) -> datetime:
            return self.value

    class FailureThenShutdown(FakeClient):
        async def create(self, **kwargs: object) -> object:
            return await super().create(**kwargs)

    async def scenario() -> None:
        shutdown = {"value": False}

        class ShutdownClient(FailureThenShutdown):
            async def create(self, **kwargs: object) -> object:
                shutdown["value"] = True
                return await super().create(**kwargs)

        shutdown_sink = DiagnosticSink()
        result = await OpenAIResponsesAdapter(
            ShutdownClient(status_error(503)),
            (make_config(),),
            now=lambda: NOW,
            diagnostic_sink=shutdown_sink,
            is_shutdown=lambda: shutdown["value"],
        ).invoke(make_request(max_attempts=2))
        assert result.status is LLMRoleStatus.CANCELLED
        assert (
            shutdown_sink.diagnostics[0].category
            is LLMProviderOperationalFailureCategory.PROVIDER_SERVER_ERROR
        )

        clock = Clock()

        class DeadlineClient(FakeClient):
            async def create(self, **kwargs: object) -> object:
                clock.value = NOW + timedelta(seconds=2)
                return await super().create(**kwargs)

        deadline_sink = DiagnosticSink()
        timed_out = await OpenAIResponsesAdapter(
            DeadlineClient(status_error(503)),
            (make_config(),),
            now=clock.now,
            diagnostic_sink=deadline_sink,
        ).invoke(make_request(deadline_at=NOW + timedelta(seconds=1), max_attempts=2))
        assert timed_out.status is LLMRoleStatus.TIMED_OUT
        assert (
            deadline_sink.diagnostics[0].category
            is LLMProviderOperationalFailureCategory.PROVIDER_SERVER_ERROR
        )

    asyncio.run(scenario())


def test_diagnostic_publication_is_secret_safe_best_effort_and_rate_limited() -> None:
    class Clock:
        value = NOW

        def now(self) -> datetime:
            return self.value

    async def scenario() -> None:
        secret = "VERY_SECRET"
        sink = DiagnosticSink()
        adapter = OpenAIResponsesAdapter(
            FakeClient(
                status_error(
                    429,
                    f"body={secret}",
                    provider_code="rate_limit_exceeded",
                    provider_request_id=f"req?token={secret}",
                ),
                status_error(
                    429,
                    f"header=Bearer {secret}",
                    provider_code="rate_limit_exceeded",
                    provider_request_id="req-safe-2",
                ),
            ),
            (make_config(instructions=f"prompt={secret}"),),
            now=lambda: NOW,
            diagnostic_sink=sink,
            diagnostic_publication_policy=LLMProviderOperationalDiagnosticPublicationPolicy(60),
        )
        await adapter.invoke(make_request(max_attempts=1))
        await adapter.invoke(make_request(max_attempts=1))
        assert len(sink.diagnostics) == 1
        rendered = str(sink.diagnostics[0].to_dict())
        assert secret not in rendered
        assert "prompt=" not in rendered
        assert "Bearer" not in rendered
        assert sink.diagnostics[0].provider_request_id is None

        sink.should_fail = True
        result = await OpenAIResponsesAdapter(
            FakeClient(status_error(500)), (make_config(),), now=lambda: NOW, diagnostic_sink=sink
        ).invoke(make_request(max_attempts=1))
        assert result.failure is not None
        assert result.failure.code is LLMFailureCode.PROVIDER_UNAVAILABLE

        shutdown = True
        shutdown_adapter = OpenAIResponsesAdapter(
            FakeClient(FakeResponse('{"ok": true}')),
            (make_config(),),
            now=lambda: Clock().now(),
            is_shutdown=lambda: shutdown,
        )
        cancelled = await shutdown_adapter.invoke(make_request())
        assert cancelled.status is LLMRoleStatus.CANCELLED

        shutdown_state = {"requested": False}

        class ShutdownAfterFirstFailure(FakeClient):
            async def create(self, **kwargs: object) -> object:
                shutdown_state["requested"] = True
                return await super().create(**kwargs)

        client = ShutdownAfterFirstFailure(
            APIConnectionError(
                request=httpx2.Request("POST", "https://api.example.invalid/v1/responses")
            ),
            FakeResponse('{"ok": true}'),
        )
        result = await OpenAIResponsesAdapter(
            client,
            (make_config(),),
            now=lambda: NOW,
            is_shutdown=lambda: shutdown_state["requested"],
        ).invoke(make_request(max_attempts=2))
        assert result.status is LLMRoleStatus.CANCELLED
        assert len(client.calls) == 1

    asyncio.run(scenario())
