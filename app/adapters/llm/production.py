from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime, timezone
from types import MappingProxyType

from app.adapters.llm.openai_responses import OpenAIResponsesAdapter, OpenAIResponsesRoleConfig
from app.domain.llm import (
    LLMFailureCode,
    LLMRoleDescriptor,
    LLMRoleFailure,
    LLMRoleRequest,
    LLMRoleResult,
    LLMRoleStatus,
    LLMTokenUsage,
)
from app.usecases.ports.llm import LLMRolePort


class UnavailableLLMRolePort:
    """論理要求を検証し、未構成の提供サービスを型付き失敗で表す本番接続。"""

    def __init__(
        self,
        roles: tuple[LLMRoleDescriptor, ...],
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        registered = {role.role_id: role for role in roles}
        if len(registered) != len(roles):
            raise ValueError("論理役割の登録は重複できません")
        self._roles = MappingProxyType(registered)
        self._now = now or (lambda: datetime.now(timezone.utc))

    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
        role = self._roles.get(request.role_id)
        if role is None or role.input_schema_id != request.input.schema_id:
            code = LLMFailureCode.POLICY_VIOLATION
            message = "役割または入力構造が登録と一致しません"
        else:
            code = LLMFailureCode.PROVIDER_UNAVAILABLE
            message = "LLM提供サービスが構成されていません"
        return LLMRoleResult(
            request_id=request.request_id,
            role_id=request.role_id,
            status=LLMRoleStatus.FAILED,
            revisions=request.revisions,
            completed_at=self._now().astimezone(timezone.utc),
            trace_id=request.trace_id,
            model_class=request.execution_policy.model_class,
            attempt_count=0,
            token_usage=LLMTokenUsage(0, 0),
            failure=LLMRoleFailure(code, message, False),
        )


def create_openai_port_from_environment(
    roles: tuple[LLMRoleDescriptor, ...],
    *,
    role_configs: tuple[OpenAIResponsesRoleConfig, ...] | None = None,
) -> LLMRolePort:
    """未構成なら中立な接続を返し、構成済みの失敗は既存契約のまま伝える。"""
    unavailable = UnavailableLLMRolePort(roles)
    if not os.environ.get("OPENAI_API_KEY"):
        return unavailable
    if role_configs is None:
        raise ValueError("構成済み提供サービスの役割設定が必要です")
    logical = {role.role_id: role for role in roles}
    if {config.role_id for config in role_configs} != set(logical):
        raise ValueError("提供サービス設定と論理役割の登録が一致しません")
    if any(
        config.input_schema_id != logical[config.role_id].input_schema_id
        or config.output_schema_id != logical[config.role_id].output_schema_id
        for config in role_configs
    ):
        raise ValueError("提供サービス設定と論理役割の構造識別が一致しません")
    return OpenAIResponsesAdapter.from_environment(role_configs)
