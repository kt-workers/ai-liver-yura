"""設定済みLLM接続を、認知用途を知らないアプリケーション境界で管理する。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol

from app.config.core_contracts import CoreConfigurationError, CoreFailureCode
from app.domain.llm import LLMRoleDescriptor, LLMRoleRequest, LLMRoleResult
from app.usecases.ports.llm import LLMRolePort


class LLMConnectionAdapter(Protocol):
    """一種類の接続設定を共通LLM Portへ変換する内部Adapter。"""

    adapter_id: str

    async def connect(
        self,
        connection: object,
        descriptors: tuple[LLMRoleDescriptor, ...],
    ) -> tuple[LLMRolePort, Callable[[], Awaitable[None]]]: ...


@dataclass(frozen=True, slots=True)
class LLMConnectionRegistry:
    """接続IDからPortを返す。認知側へAdapterを公開しない。"""

    _ports: MappingProxyType[str, LLMRolePort]
    _close_actions: tuple[Callable[[], Awaitable[None]], ...] = field(repr=False)
    _close_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        ports = dict(self._ports)
        if not ports or any(
            not isinstance(connection_id, str)
            or not connection_id.strip()
            or not callable(getattr(port, "invoke", None))
            for connection_id, port in ports.items()
        ):
            raise CoreConfigurationError(CoreFailureCode.PROVIDER_MAPPING_FAILED)
        object.__setattr__(self, "_ports", MappingProxyType(ports))

    def port(self, connection_id: str) -> LLMRolePort:
        try:
            return self._ports[connection_id]
        except KeyError:
            raise CoreConfigurationError(CoreFailureCode.PROVIDER_MAPPING_FAILED) from None

    async def close(self) -> None:
        if self._close_task is None:
            object.__setattr__(self, "_close_task", asyncio.create_task(self._close()))
        assert self._close_task is not None
        await asyncio.shield(self._close_task)

    async def _close(self) -> None:
        failed = False
        cancelled = False
        for action in reversed(self._close_actions):
            try:
                await action()
            except asyncio.CancelledError:
                cancelled = True
            except Exception:
                failed = True
        if cancelled:
            raise asyncio.CancelledError
        if failed:
            raise CoreConfigurationError(CoreFailureCode.PROVIDER_MAPPING_FAILED)


@dataclass(frozen=True, slots=True)
class LLMConnectionRouter:
    """Roleの内部識別子を、構成済み接続へ閉じ込める共通Port。"""

    _ports_by_role: MappingProxyType[str, LLMRolePort]

    def __init__(self, ports_by_role: dict[str, LLMRolePort]) -> None:
        ports = dict(ports_by_role)
        if not ports or any(
            not isinstance(role_id, str)
            or not role_id.strip()
            or not callable(getattr(port, "invoke", None))
            for role_id, port in ports.items()
        ):
            raise CoreConfigurationError(CoreFailureCode.PROVIDER_MAPPING_FAILED)
        object.__setattr__(self, "_ports_by_role", MappingProxyType(ports))

    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
        try:
            port = self._ports_by_role[request.role_id]
        except (AttributeError, KeyError):
            raise CoreConfigurationError(CoreFailureCode.PROVIDER_MAPPING_FAILED) from None
        return await port.invoke(request)


def route_llm_connections(
    registry: LLMConnectionRegistry,
    role_connections: tuple[tuple[LLMRoleDescriptor, str], ...],
) -> LLMConnectionRouter:
    """各Ownerの接続参照を検証し、Roleの配送詳細を構成層だけへ閉じ込める。"""
    if not isinstance(registry, LLMConnectionRegistry):
        raise CoreConfigurationError(CoreFailureCode.PROVIDER_MAPPING_FAILED)
    ports: dict[str, LLMRolePort] = {}
    for descriptor, connection_id in role_connections:
        if (
            not isinstance(descriptor, LLMRoleDescriptor)
            or not isinstance(connection_id, str)
            or not connection_id.strip()
            or descriptor.role_id in ports
        ):
            raise CoreConfigurationError(CoreFailureCode.PROVIDER_MAPPING_FAILED)
        ports[descriptor.role_id] = registry.port(connection_id)
    return LLMConnectionRouter(ports)


