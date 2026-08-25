from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Protocol, cast

from jsonschema import ValidationError, validate
from openai import APIConnectionError, APIStatusError, APITimeoutError

from app.domain.llm import (
    LLMFailureCode,
    LLMFailurePolicy,
    LLMModelClass,
    LLMReasoningEffort,
    LLMRoleFailure,
    LLMRoleRequest,
    LLMRoleResult,
    LLMRoleStatus,
    LLMTokenUsage,
    StructuredPayload,
)

from .operational_diagnostics import (
    LLMProviderOperationalDiagnostic,
    LLMProviderOperationalDiagnosticPublicationPolicy,
    LLMProviderOperationalDiagnosticPublisher,
    LLMProviderOperationalDiagnosticSink,
    LLMProviderOperationalFailureCategory,
    LLMProviderSanitizedDetailCode,
)


class ResponsesClient(Protocol):
    async def create(self, **kwargs: object) -> object: ...


@dataclass(frozen=True, slots=True)
class OpenAIResponsesModelPolicy:
    """Roleに許可したmodel classをProvider固有設定へ解決する不変policy。"""

    model: str
    reasoning_by_effort: Mapping[LLMReasoningEffort, str]

    def __post_init__(self) -> None:
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError("Provider modelは空にできません")
        if not isinstance(self.reasoning_by_effort, Mapping):
            raise ValueError("reasoning mappingはMappingでなければなりません")
        reasoning_by_effort = dict(self.reasoning_by_effort)
        if not reasoning_by_effort:
            raise ValueError("reasoning mappingは空にできません")
        if any(
            not isinstance(effort, LLMReasoningEffort)
            or not isinstance(value, str)
            or not value.strip()
            for effort, value in reasoning_by_effort.items()
        ):
            raise ValueError("reasoning mappingが不正です")
        object.__setattr__(
            self,
            "reasoning_by_effort",
            MappingProxyType(reasoning_by_effort),
        )


@dataclass(frozen=True, slots=True)
class OpenAIResponsesRoleConfig:
    role_id: str
    model_policies: Mapping[LLMModelClass, OpenAIResponsesModelPolicy]
    input_schema_id: str
    output_schema_id: str
    provider_output_format_name: str
    output_json_schema: Mapping[str, object]
    instructions: str
    failure_policy: LLMFailurePolicy

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (
                self.role_id,
                self.input_schema_id,
                self.output_schema_id,
                self.provider_output_format_name,
                self.instructions,
            )
        ):
            raise ValueError("Role設定の文字列は空にできません")
        if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.provider_output_format_name) is None:
            raise ValueError("Provider output format nameがOpenAI制約に一致しません")
        if not isinstance(self.output_json_schema, Mapping):
            raise ValueError("出力JSON Schemaはobjectでなければなりません")
        if not isinstance(self.model_policies, Mapping):
            raise ValueError("model policyはMappingでなければなりません")
        model_policies = dict(self.model_policies)
        if not model_policies or any(
            not isinstance(model_class, LLMModelClass)
            or not isinstance(policy, OpenAIResponsesModelPolicy)
            for model_class, policy in model_policies.items()
        ):
            raise ValueError("model policyが不正です")
        object.__setattr__(self, "model_policies", MappingProxyType(model_policies))


@dataclass(frozen=True, slots=True)
class _ProviderFailureClassification:
    code: LLMFailureCode
    retryable: bool
    category: LLMProviderOperationalFailureCategory
    http_status: int | None
    provider_request_id: str | None
    sanitized_detail_code: LLMProviderSanitizedDetailCode


class _ProviderProtocolError(ValueError):
    """Provider成功応答のenvelopeがAdapter契約に適合しない。"""


class OpenAIResponsesAdapter:
    """OpenAI Responses APIを論理Role Portへ隔離して接続するAdapter。"""

    def __init__(
        self,
        client: ResponsesClient,
        role_configs: tuple[OpenAIResponsesRoleConfig, ...],
        *,
        now: Callable[[], datetime] | None = None,
        diagnostic_sink: LLMProviderOperationalDiagnosticSink | None = None,
        diagnostic_publication_policy: LLMProviderOperationalDiagnosticPublicationPolicy
        | None = None,
        is_shutdown: Callable[[], bool] | None = None,
    ) -> None:
        configs = {config.role_id: config for config in role_configs}
        if len(configs) != len(role_configs):
            raise ValueError("Role設定は重複できません")
        provider_format_names = {config.provider_output_format_name for config in role_configs}
        if len(provider_format_names) != len(role_configs):
            raise ValueError("Provider output format nameはRole間で重複できません")
        self._client = client
        self._role_configs = configs
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._diagnostics = LLMProviderOperationalDiagnosticPublisher(
            diagnostic_sink,
            diagnostic_publication_policy or LLMProviderOperationalDiagnosticPublicationPolicy(),
            now=self._now,
        )
        self._is_shutdown = is_shutdown or (lambda: False)

    @classmethod
    def from_environment(
        cls, role_configs: tuple[OpenAIResponsesRoleConfig, ...]
    ) -> OpenAIResponsesAdapter:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEYが設定されていません")
        try:
            from openai import AsyncOpenAI
        except ImportError as error:
            raise RuntimeError("openai SDKがインストールされていません") from error
        return cls(cast(ResponsesClient, AsyncOpenAI(api_key=api_key).responses), role_configs)

    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
        started_at = self._now()
        config = self._role_configs.get(request.role_id)
        if config is None or config.input_schema_id != request.input.schema_id:
            return self._failure(
                request,
                LLMFailureCode.POLICY_VIOLATION,
                "Roleまたは入力schemaが未登録です",
                0,
                started_at,
            )
        provider_policy = config.model_policies.get(request.execution_policy.model_class)
        if provider_policy is None or (
            request.execution_policy.reasoning_effort not in provider_policy.reasoning_by_effort
        ):
            return self._failure(
                request,
                LLMFailureCode.POLICY_VIOLATION,
                "RoleのProvider model policyが未登録です",
                0,
                started_at,
            )
        if self._is_shutdown():
            return await self._cancelled(request, config, provider_policy, 0, started_at)
        for attempt in range(1, request.execution_policy.max_attempts + 1):
            timeout = self._remaining_timeout(request)
            if timeout <= 0:
                return await self._timed_out(
                    request,
                    config,
                    provider_policy,
                    attempt - 1,
                    started_at,
                    LLMProviderSanitizedDetailCode.CLIENT_DEADLINE_EXCEEDED,
                )
            try:
                response = await asyncio.wait_for(
                    self._client.create(
                        **self._request_arguments(request, config, provider_policy)
                    ),
                    timeout=timeout,
                )
                output = self._parse_output(response, config)
                completed_at = self._now()
                return LLMRoleResult(
                    request.request_id,
                    request.role_id,
                    LLMRoleStatus.SUCCEEDED,
                    request.revisions,
                    completed_at,
                    request.trace_id,
                    request.execution_policy.model_class,
                    attempt,
                    self._token_usage(response),
                    output=output,
                    started_at=started_at,
                )
            except asyncio.TimeoutError:
                classification = _ProviderFailureClassification(
                    LLMFailureCode.PROVIDER_UNAVAILABLE,
                    True,
                    LLMProviderOperationalFailureCategory.REQUEST_TIMEOUT,
                    None,
                    None,
                    LLMProviderSanitizedDetailCode.CLIENT_TIMEOUT,
                )
                result, retry = await self._handle_provider_failure(
                    request, config, provider_policy, classification, attempt, started_at
                )
                if retry:
                    continue
                assert result is not None
                return result
            except asyncio.CancelledError:
                return await self._cancelled(request, config, provider_policy, attempt, started_at)
            except _ProviderProtocolError:
                classification = _ProviderFailureClassification(
                    LLMFailureCode.PROVIDER_ERROR,
                    False,
                    LLMProviderOperationalFailureCategory.PROVIDER_PROTOCOL_ERROR,
                    None,
                    None,
                    LLMProviderSanitizedDetailCode.UNKNOWN,
                )
                result, retry = await self._handle_provider_failure(
                    request, config, provider_policy, classification, attempt, started_at
                )
                if retry:
                    continue
                assert result is not None
                return result
            except (ValidationError, ValueError):
                return self._failure(
                    request,
                    LLMFailureCode.SCHEMA_INVALID,
                    "Provider出力がstrict JSON schemaに一致しません",
                    attempt,
                    started_at,
                )
            except Exception as error:
                classification = self._classify_provider_failure(error)
                result, retry = await self._handle_provider_failure(
                    request, config, provider_policy, classification, attempt, started_at
                )
                if retry:
                    continue
                assert result is not None
                return result
        raise AssertionError("到達不能なretry状態です")

    def _request_arguments(
        self,
        request: LLMRoleRequest,
        config: OpenAIResponsesRoleConfig,
        provider_policy: OpenAIResponsesModelPolicy,
    ) -> dict[str, object]:
        return {
            "model": provider_policy.model,
            "instructions": config.instructions,
            "input": json.dumps(request.input.to_dict()["value"], ensure_ascii=False),
            "max_output_tokens": request.execution_policy.max_output_tokens,
            "temperature": request.execution_policy.temperature,
            "reasoning": {
                "effort": provider_policy.reasoning_by_effort[
                    request.execution_policy.reasoning_effort
                ]
            },
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": config.provider_output_format_name,
                    "strict": True,
                    "schema": dict(config.output_json_schema),
                }
            },
        }

    def _parse_output(
        self, response: object, config: OpenAIResponsesRoleConfig
    ) -> StructuredPayload:
        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str):
            raise _ProviderProtocolError("output_textがありません")
        value = json.loads(output_text)
        if not isinstance(value, dict):
            raise ValueError("出力はJSON objectではありません")
        validate(instance=value, schema=dict(config.output_json_schema))
        return StructuredPayload(config.output_schema_id, value)

    async def _handle_provider_failure(
        self,
        request: LLMRoleRequest,
        config: OpenAIResponsesRoleConfig,
        provider_policy: OpenAIResponsesModelPolicy,
        classification: _ProviderFailureClassification,
        attempt: int,
        started_at: datetime,
    ) -> tuple[LLMRoleResult | None, bool]:
        retryable = self._retry_allowed(request, config, classification, attempt)
        self._publish_diagnostic(
            request, config, provider_policy, classification, attempt, retryable
        )
        if self._is_shutdown():
            return (
                await self._cancelled(
                    request, config, provider_policy, attempt, started_at, publish=False
                ),
                False,
            )
        if self._remaining_timeout(request) <= 0:
            return (
                await self._timed_out(
                    request,
                    config,
                    provider_policy,
                    attempt,
                    started_at,
                    LLMProviderSanitizedDetailCode.CLIENT_DEADLINE_EXCEEDED,
                    publish=False,
                ),
                False,
            )
        if retryable:
            return None, True
        return (
            self._failure(
                request,
                classification.code,
                "Provider呼出に失敗しました",
                attempt,
                started_at,
                retryable=False,
            ),
            False,
        )

    def _remaining_timeout(self, request: LLMRoleRequest) -> float:
        timeout = request.execution_policy.timeout_seconds
        if request.deadline_at is not None:
            timeout = min(timeout, (request.deadline_at - self._now()).total_seconds())
        return timeout

    def _retry_allowed(
        self,
        request: LLMRoleRequest,
        config: OpenAIResponsesRoleConfig,
        classification: _ProviderFailureClassification,
        attempt: int,
    ) -> bool:
        return (
            classification.retryable
            and config.failure_policy is LLMFailurePolicy.RETRY_BOUNDED
            and attempt < request.execution_policy.max_attempts
            and self._remaining_timeout(request) > 0
            and not self._is_shutdown()
        )

    @staticmethod
    def _classify_provider_failure(error: Exception) -> _ProviderFailureClassification:
        if isinstance(error, (APIConnectionError, APITimeoutError)):
            if isinstance(error, APITimeoutError):
                return _ProviderFailureClassification(
                    LLMFailureCode.PROVIDER_UNAVAILABLE,
                    True,
                    LLMProviderOperationalFailureCategory.REQUEST_TIMEOUT,
                    None,
                    None,
                    LLMProviderSanitizedDetailCode.SDK_TIMEOUT,
                )
            return _ProviderFailureClassification(
                LLMFailureCode.PROVIDER_UNAVAILABLE,
                True,
                LLMProviderOperationalFailureCategory.TRANSPORT_UNAVAILABLE,
                None,
                None,
                LLMProviderSanitizedDetailCode.SDK_CONNECTION,
            )
        if isinstance(error, APIStatusError):
            status_code = error.status_code
            provider_request_id = _safe_provider_request_id(error)
            if status_code == 408:
                return _ProviderFailureClassification(
                    LLMFailureCode.PROVIDER_UNAVAILABLE,
                    True,
                    LLMProviderOperationalFailureCategory.REQUEST_TIMEOUT,
                    status_code,
                    provider_request_id,
                    LLMProviderSanitizedDetailCode.HTTP_408,
                )
            if status_code == 429:
                safe_code = _safe_provider_code(error)
                if safe_code in {"rate_limit_exceeded", "rate_limit"}:
                    return _ProviderFailureClassification(
                        LLMFailureCode.PROVIDER_UNAVAILABLE,
                        True,
                        LLMProviderOperationalFailureCategory.RATE_LIMITED_TRANSIENT,
                        status_code,
                        provider_request_id,
                        LLMProviderSanitizedDetailCode.HTTP_429_TRANSIENT,
                    )
                if safe_code in {"insufficient_quota", "billing_hard_limit_reached"}:
                    return _ProviderFailureClassification(
                        LLMFailureCode.PROVIDER_UNAVAILABLE,
                        False,
                        LLMProviderOperationalFailureCategory.QUOTA_OR_BILLING_EXHAUSTED,
                        status_code,
                        provider_request_id,
                        LLMProviderSanitizedDetailCode.HTTP_429_QUOTA_OR_BILLING,
                    )
                return _ProviderFailureClassification(
                    LLMFailureCode.PROVIDER_UNAVAILABLE,
                    False,
                    LLMProviderOperationalFailureCategory.UNKNOWN_PROVIDER_FAILURE,
                    status_code,
                    provider_request_id,
                    LLMProviderSanitizedDetailCode.HTTP_429_UNCLASSIFIED,
                )
            if 500 <= status_code <= 599:
                return _ProviderFailureClassification(
                    LLMFailureCode.PROVIDER_UNAVAILABLE,
                    True,
                    LLMProviderOperationalFailureCategory.PROVIDER_SERVER_ERROR,
                    status_code,
                    provider_request_id,
                    LLMProviderSanitizedDetailCode.HTTP_5XX,
                )
            if status_code == 401:
                return _ProviderFailureClassification(
                    LLMFailureCode.PROVIDER_ERROR,
                    False,
                    LLMProviderOperationalFailureCategory.AUTHENTICATION_OR_PERMISSION_FAILED,
                    status_code,
                    provider_request_id,
                    LLMProviderSanitizedDetailCode.HTTP_AUTHENTICATION,
                )
            if status_code == 403:
                return _ProviderFailureClassification(
                    LLMFailureCode.PROVIDER_ERROR,
                    False,
                    LLMProviderOperationalFailureCategory.AUTHENTICATION_OR_PERMISSION_FAILED,
                    status_code,
                    provider_request_id,
                    LLMProviderSanitizedDetailCode.HTTP_PERMISSION,
                )
            return _ProviderFailureClassification(
                LLMFailureCode.PROVIDER_ERROR,
                False,
                LLMProviderOperationalFailureCategory.PROVIDER_REQUEST_REJECTED,
                status_code,
                provider_request_id,
                LLMProviderSanitizedDetailCode.HTTP_REQUEST_REJECTED,
            )
        return _ProviderFailureClassification(
            LLMFailureCode.PROVIDER_ERROR,
            False,
            LLMProviderOperationalFailureCategory.UNKNOWN_PROVIDER_FAILURE,
            None,
            None,
            LLMProviderSanitizedDetailCode.UNKNOWN,
        )

    async def _timed_out(
        self,
        request: LLMRoleRequest,
        config: OpenAIResponsesRoleConfig,
        provider_policy: OpenAIResponsesModelPolicy,
        attempts: int,
        started_at: datetime,
        detail_code: LLMProviderSanitizedDetailCode,
        *,
        publish: bool = True,
    ) -> LLMRoleResult:
        classification = _ProviderFailureClassification(
            LLMFailureCode.TIMEOUT,
            False,
            LLMProviderOperationalFailureCategory.REQUEST_TIMEOUT,
            None,
            None,
            detail_code,
        )
        if publish:
            self._publish_diagnostic(
                request, config, provider_policy, classification, attempts, False
            )
        return LLMRoleResult(
            request.request_id,
            request.role_id,
            LLMRoleStatus.TIMED_OUT,
            request.revisions,
            self._now(),
            request.trace_id,
            request.execution_policy.model_class,
            attempts,
            LLMTokenUsage(0, 0),
            failure=LLMRoleFailure(LLMFailureCode.TIMEOUT, "Provider呼出がtimeoutしました"),
            started_at=started_at,
        )

    async def _cancelled(
        self,
        request: LLMRoleRequest,
        config: OpenAIResponsesRoleConfig,
        provider_policy: OpenAIResponsesModelPolicy,
        attempts: int,
        started_at: datetime,
        *,
        publish: bool = True,
    ) -> LLMRoleResult:
        classification = _ProviderFailureClassification(
            LLMFailureCode.CANCELLED,
            False,
            LLMProviderOperationalFailureCategory.CANCELLED,
            None,
            None,
            LLMProviderSanitizedDetailCode.CANCELLED_BY_CALLER,
        )
        if publish:
            self._publish_diagnostic(
                request, config, provider_policy, classification, attempts, False
            )
        return LLMRoleResult(
            request.request_id,
            request.role_id,
            LLMRoleStatus.CANCELLED,
            request.revisions,
            self._now(),
            request.trace_id,
            request.execution_policy.model_class,
            attempts,
            LLMTokenUsage(0, 0),
            failure=LLMRoleFailure(LLMFailureCode.CANCELLED, "Provider呼出は取り消されました"),
            started_at=started_at,
        )

    def _publish_diagnostic(
        self,
        request: LLMRoleRequest,
        config: OpenAIResponsesRoleConfig,
        provider_policy: OpenAIResponsesModelPolicy,
        classification: _ProviderFailureClassification,
        attempt: int,
        retryable: bool,
    ) -> None:
        self._diagnostics.publish(
            LLMProviderOperationalDiagnostic(
                f"llm-diagnostic:{request.request_id}:{attempt}:{classification.category.value}",
                request.request_id,
                request.role_id,
                "openai_responses",
                provider_policy.model,
                classification.category,
                classification.http_status,
                classification.provider_request_id,
                attempt,
                retryable,
                self._now(),
                classification.sanitized_detail_code,
            )
        )

    def _failure(
        self,
        request: LLMRoleRequest,
        code: LLMFailureCode,
        message: str,
        attempts: int,
        started_at: datetime,
        *,
        retryable: bool = False,
    ) -> LLMRoleResult:
        return LLMRoleResult(
            request.request_id,
            request.role_id,
            LLMRoleStatus.FAILED,
            request.revisions,
            self._now(),
            request.trace_id,
            request.execution_policy.model_class,
            attempts,
            LLMTokenUsage(0, 0),
            failure=LLMRoleFailure(code, message, retryable),
            started_at=started_at,
        )

    @staticmethod
    def _token_usage(response: object) -> LLMTokenUsage:
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "input_tokens", 0)
        output_tokens = getattr(usage, "output_tokens", 0)
        if type(input_tokens) is not int or input_tokens < 0:
            input_tokens = 0
        if type(output_tokens) is not int or output_tokens < 0:
            output_tokens = 0
        return LLMTokenUsage(input_tokens, output_tokens)


_SAFE_PROVIDER_REQUEST_ID = re.compile(r"[A-Za-z0-9._:-]{1,256}")
_SAFE_PROVIDER_CODES = frozenset(
    {"rate_limit_exceeded", "rate_limit", "insufficient_quota", "billing_hard_limit_reached"}
)


def _safe_provider_code(error: APIStatusError) -> str | None:
    value = getattr(error, "code", None)
    if not isinstance(value, str) or value not in _SAFE_PROVIDER_CODES:
        return None
    return value


def _safe_provider_request_id(error: APIStatusError) -> str | None:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    value = None if headers is None else headers.get("x-request-id")
    if not isinstance(value, str) or _SAFE_PROVIDER_REQUEST_ID.fullmatch(value) is None:
        return None
    return value
