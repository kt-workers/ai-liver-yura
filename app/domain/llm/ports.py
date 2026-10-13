"""Domainが必要とするLLM呼出し能力の抽象境界。"""

from __future__ import annotations

from typing import Protocol

from .contracts import LLMRoleRequest, LLMRoleResult


class LLMRolePort(Protocol):
    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult: ...
