"""既存LLM接続の外側で、役割ごとの遅延と指定失敗だけを注入する。"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from app.domain.llm import (
    LLMFailureCode,
    LLMRoleFailure,
    LLMRoleRequest,
    LLMRoleResult,
    LLMRoleStatus,
    LLMTokenUsage,
)
from app.usecases.ports.llm import LLMRolePort

from .contracts import InjectedFailure, identifier
from .runtime import RunContext


@dataclass(frozen=True)
class LabLLMPortFactory:
    """実行固有の診断収集先を使って接続を構成する信頼済み起動処理。

    新規クライアントを所有する場合はcontext.add_cleanupへ終了処理を登録する。
    """

    create: Callable[[RunContext], LLMRolePort]


def resolve_port(port: LLMRolePort | LabLLMPortFactory, context: RunContext) -> LLMRolePort:
    return port.create(context) if isinstance(port, LabLLMPortFactory) else port


class ObservedLLMRolePort:
    def __init__(self, context: RunContext, port: LLMRolePort, stages: Mapping[str, str]) -> None:
        if not stages:
            raise ValueError("観測する役割と接続段階を指定してください")
        for role, stage in stages.items():
            identifier(role)
            identifier(stage)
        self._context, self._port = context, port
        self._stages = MappingProxyType(dict(stages))

    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
        stage = self._stages.get(request.role_id)
        if stage is None:
            raise ValueError("観測する役割に登録されていません")

        async def invoke() -> LLMRoleResult:
            injected = self._context.take_failure(stage)
            if injected is None:
                return await self._port.invoke(request)
            status, code = {
                InjectedFailure.PROVIDER_UNAVAILABLE: (
                    LLMRoleStatus.FAILED,
                    LLMFailureCode.PROVIDER_UNAVAILABLE,
                ),
                InjectedFailure.TIMEOUT: (LLMRoleStatus.TIMED_OUT, LLMFailureCode.TIMEOUT),
                InjectedFailure.CANCELLED: (LLMRoleStatus.CANCELLED, LLMFailureCode.CANCELLED),
            }[injected]
            return LLMRoleResult(
                request.request_id,
                request.role_id,
                status,
                request.revisions,
                request.created_at,
                request.trace_id,
                request.execution_policy.model_class,
                0,
                LLMTokenUsage(0, 0),
                failure=LLMRoleFailure(code, "検証条件で指定した失敗です", False),
            )

        return await self._context.invoke_port(stage, invoke)
