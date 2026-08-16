from __future__ import annotations

from typing import Protocol

from app.domain.llm import LLMRoleRequest, LLMRoleResult


class LLMRolePort(Protocol):
    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult: ...
