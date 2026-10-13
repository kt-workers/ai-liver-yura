from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from app.domain.llm import LLMRoleDescriptor, LLMRoleRequest, LLMRoleResult


class LLMRolePort(Protocol):
    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult: ...


class LLMConnectionAdapter(Protocol):
    """一種類の接続設定を共通LLM Portへ変換する内部Adapter。"""

    adapter_id: str

    async def connect(
        self,
        connection: object,
        descriptors: tuple[LLMRoleDescriptor, ...],
    ) -> tuple[LLMRolePort, Callable[[], Awaitable[None]]]: ...
