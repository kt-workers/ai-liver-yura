from __future__ import annotations

import asyncio
import json
import os
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
                self.instructions,
            )
        ):
            raise ValueError("Role設定の文字列は空にできません")
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


class OpenAIResponsesAdapter:
    """OpenAI Responses APIを論理Role Portへ隔離して接続するAdapter。"""

    def __init__(
        self,
        client: ResponsesClient,
        role_configs: tuple[OpenAIResponsesRoleConfig, ...],
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        configs = {config.role_id: config for config in role_configs}
        if len(configs) != len(role_configs):
            raise ValueError("Role設定は重複できません")
        self._client = client
        self._role_configs = configs
        self._now = now or (lambda: datetime.now(timezone.utc))

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
        for attempt in range(1, request.execution_policy.max_attempts + 1):
            timeout = self._remaining_timeout(request)
            if timeout <= 0:
                return self._timed_out(request, attempt - 1, started_at)
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
                return self._timed_out(request, attempt, started_at)
            except asyncio.CancelledError:
                return LLMRoleResult(
                    request.request_id, request.role_id, LLMRoleStatus.CANCELLED, request.revisions,
                    self._now(),
                    request.trace_id,
                    request.execution_policy.model_class,
                    attempt,
                    LLMTokenUsage(0, 0),
                    failure=LLMRoleFailure(
                        LLMFailureCode.CANCELLED, "Provider呼出は取り消されました"
                    ),
                    started_at=started_at,
                )
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
                if (
                    classification.retryable
                    and request.execution_policy.max_attempts > attempt
                    and request.execution_policy.max_attempts > 1
                    and self._retry_allowed(config)
                ):
                    continue
                return self._failure(
                    request,
                    classification.code,
                    "Provider呼出に失敗しました",
                    attempt,
                    started_at,
                    retryable=classification.retryable,
                )
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
                    "name": config.output_schema_id,
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
            raise ValueError("output_textがありません")
        value = json.loads(output_text)
        if not isinstance(value, dict):
            raise ValueError("出力はJSON objectではありません")
        validate(instance=value, schema=dict(config.output_json_schema))
        return StructuredPayload(config.output_schema_id, value)

    def _remaining_timeout(self, request: LLMRoleRequest) -> float:
        timeout = request.execution_policy.timeout_seconds
        if request.deadline_at is not None:
            timeout = min(timeout, (request.deadline_at - self._now()).total_seconds())
        return timeout

    @staticmethod
    def _retry_allowed(config: OpenAIResponsesRoleConfig) -> bool:
        return config.failure_policy is LLMFailurePolicy.RETRY_BOUNDED

    @staticmethod
    def _classify_provider_failure(error: Exception) -> _ProviderFailureClassification:
        if isinstance(error, (APIConnectionError, APITimeoutError)):
            return _ProviderFailureClassification(LLMFailureCode.PROVIDER_UNAVAILABLE, True)
        if isinstance(error, APIStatusError):
            status_code = error.status_code
            if status_code == 408 or status_code == 429 or 500 <= status_code <= 599:
                return _ProviderFailureClassification(LLMFailureCode.PROVIDER_UNAVAILABLE, True)
        return _ProviderFailureClassification(LLMFailureCode.PROVIDER_ERROR, False)

    def _timed_out(
        self, request: LLMRoleRequest, attempts: int, started_at: datetime
    ) -> LLMRoleResult:
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

    def _failure(
        self, request: LLMRoleRequest, code: LLMFailureCode, message: str, attempts: int,
        started_at: datetime, *, retryable: bool = False,
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
