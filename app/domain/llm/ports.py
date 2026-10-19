"""Domain Ownerが利用するLLMの抽象Port。"""

from __future__ import annotations

from typing import Protocol

from app.domain.llm.contracts import LLMRoleRequest, LLMRoleResult


class LLMRolePort(Protocol):
    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult: ...
