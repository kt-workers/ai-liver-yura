"""設定済みLLM接続を実際のAdapterへ結線する外側の組立処理。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol
from types import MappingProxyType

from app.config.core_contracts import CoreConfigurationError, CoreFailureCode
from app.config.llm_connections import LLMConnectionConfig, LLMConnectionsConfig
from app.domain.llm import LLMRoleDescriptor
from app.infrastructure.llm.connections import LLMConnectionRegistry
from app.usecases.ports.llm import LLMRolePort


class LLMConnectionAdapter(Protocol):
    """構成済みの接続設定からProvider固有Portを取得する外側の契約。"""

    adapter_id: str

    async def connect(
        self,
        connection: LLMConnectionConfig,
        descriptors: tuple[LLMRoleDescriptor, ...],
    ) -> tuple[LLMRolePort, Callable[[], Awaitable[None]]]: ...


async def create_llm_connection_registry(
    configuration: LLMConnectionsConfig,
    descriptors: tuple[LLMRoleDescriptor, ...],
    adapters: tuple[LLMConnectionAdapter, ...],
) -> LLMConnectionRegistry:
    """外部接続を生成し、途中失敗時は生成済みの接続を回収する。"""
    by_adapter = {adapter.adapter_id: adapter for adapter in adapters}
    if len(by_adapter) != len(adapters):
        raise CoreConfigurationError(CoreFailureCode.PROVIDER_MAPPING_FAILED)
    ports: dict[str, LLMRolePort] = {}
    close_actions: list[Callable[[], Awaitable[None]]] = []
    try:
        for connection in configuration.connections:
            adapter = by_adapter.get(connection.adapter_id)
            if adapter is None:
                raise CoreConfigurationError(CoreFailureCode.PROVIDER_MAPPING_FAILED)
            port, close = await adapter.connect(connection, descriptors)
            if not callable(getattr(port, "invoke", None)) or not callable(close):
                raise CoreConfigurationError(CoreFailureCode.PROVIDER_MAPPING_FAILED)
            ports[connection.connection_id] = port
            close_actions.append(close)
        return LLMConnectionRegistry(MappingProxyType(ports), tuple(close_actions))
    except BaseException:
        cleanup_failed = False
        cleanup_cancelled = False
        for close in reversed(close_actions):
            try:
                await close()
            except asyncio.CancelledError:
                cleanup_cancelled = True
            except Exception:
                cleanup_failed = True
        if cleanup_cancelled:
            raise asyncio.CancelledError from None
        if cleanup_failed:
            raise CoreConfigurationError(CoreFailureCode.PROVIDER_MAPPING_FAILED) from None
        raise
