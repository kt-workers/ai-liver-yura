from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol, cast

from jsonschema import ValidationError, validate

from app.domain.llm import (
    LLMFailureCode,
    LLMFailurePolicy,
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
class OpenAIResponsesRoleConfig:
    role_id: str
    model: str
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
                self.model,
                self.input_schema_id,
                self.output_schema_id,
                self.instructions,
            )
        ):
            raise ValueError("Role設定の文字列は空にできません")
        if not isinstance(self.output_json_schema, Mapping):
            raise ValueError("出力JSON Schemaはobjectでなければなりません")


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
        for attempt in range(1, request.execution_policy.max_attempts + 1):
            timeout = self._remaining_timeout(request)
            if timeout <= 0:
                return self._timed_out(request, attempt - 1, started_at)
            try:
                response = await asyncio.wait_for(
                    self._client.create(**self._request_arguments(request, config)), timeout=timeout
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
                if (
                    request.execution_policy.max_attempts > attempt
                    and request.execution_policy.max_attempts > 1
                    and self._retry_allowed(config)
                ):
                    continue
                code = self._provider_failure_code(error)
                return self._failure(
                    request,
                    code,
                    "Provider呼出に失敗しました",
                    attempt,
                    started_at,
                    retryable=self._retry_allowed(config),
                )
        raise AssertionError("到達不能なretry状態です")

    def _request_arguments(
        self, request: LLMRoleRequest, config: OpenAIResponsesRoleConfig
    ) -> dict[str, object]:
        return {
            "model": config.model,
            "instructions": config.instructions,
            "input": json.dumps(request.input.to_dict()["value"], ensure_ascii=False),
            "max_output_tokens": request.execution_policy.max_output_tokens,
            "temperature": request.execution_policy.temperature,
            "reasoning": {"effort": request.execution_policy.reasoning_effort.value},
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
    def _provider_failure_code(error: Exception | None = None) -> LLMFailureCode:
        status_code = getattr(error, "status_code", None)
        if status_code in {408, 429, 500, 502, 503, 504}:
            return LLMFailureCode.PROVIDER_UNAVAILABLE
        return LLMFailureCode.PROVIDER_ERROR

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
