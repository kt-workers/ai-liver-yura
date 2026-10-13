"""設定済みLLM接続の資源所有とRole配送をInfrastructureに閉じ込める。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from types import MappingProxyType

from app.config.core_contracts import CoreConfigurationError, CoreFailureCode
from app.domain.llm import LLMRoleDescriptor, LLMRoleRequest, LLMRoleResult
from app.usecases.ports.llm import LLMRolePort


class LLMConnectionRegistry:
    """外部Portと終了処理を所有する接続レジストリ。"""

    __slots__ = ("_ports", "_close_actions", "_close_task")

    def __init__(
        self,
        ports: Mapping[str, LLMRolePort],
        close_actions: tuple[Callable[[], Awaitable[None]], ...],
    ) -> None:
        self._ports: MappingProxyType[str, LLMRolePort]
        self._close_actions = tuple(close_actions)
        self._close_task: asyncio.Task[None] | None = None
        port_values = dict(ports)
        if not port_values or any(
            not isinstance(connection_id, str)
            or not connection_id.strip()
            or not callable(getattr(port, "invoke", None))
            for connection_id, port in port_values.items()
        ):
            raise CoreConfigurationError(CoreFailureCode.PROVIDER_MAPPING_FAILED)
        self._ports = MappingProxyType(port_values)

    def port(self, connection_id: str) -> LLMRolePort:
        try:
            return self._ports[connection_id]
        except KeyError:
            raise CoreConfigurationError(CoreFailureCode.PROVIDER_MAPPING_FAILED) from None

    async def close(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close())
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


class LLMConnectionRouter:
    """構成済みのRole接続を実行時の要求先へ配送するAdapter。"""

    __slots__ = ("_ports_by_role",)

    def __init__(self, ports_by_role: dict[str, LLMRolePort]) -> None:
        ports = dict(ports_by_role)
        if not ports or any(
            not isinstance(role_id, str)
            or not role_id.strip()
            or not callable(getattr(port, "invoke", None))
            for role_id, port in ports.items()
        ):
            raise CoreConfigurationError(CoreFailureCode.PROVIDER_MAPPING_FAILED)
        self._ports_by_role: MappingProxyType[str, LLMRolePort] = MappingProxyType(ports)

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


