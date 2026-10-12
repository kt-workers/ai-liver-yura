from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import pytest

from app.composition.llm_connections import create_llm_connection_registry
from app.composition.system_cognition_configuration import CoreRunIdentity
from app.config.core_contracts import CoreConfigurationError
from app.config.llm_connections import LLMConnectionConfig, LLMConnectionsConfig
from app.domain.llm import LLMRoleDescriptor


class Port:
    async def invoke(self, request: object) -> object:
        return request


@dataclass
class Adapter:
    adapter_id: str
    events: list[str]
    fail_for: str | None = None
    fail_close: bool = False

    async def connect(
        self, connection: LLMConnectionConfig, descriptors: tuple[LLMRoleDescriptor, ...]
    ) -> tuple[Port, Callable[[], Awaitable[None]]]:
        self.events.append(f"connect:{connection.connection_id}")
        if connection.connection_id == self.fail_for:
            raise RuntimeError("接続失敗")

        async def close() -> None:
            self.events.append(f"close:{connection.connection_id}")
            if self.fail_close:
                raise RuntimeError("回収失敗")

        return Port(), close


def configuration(*ids: str) -> LLMConnectionsConfig:
    return LLMConnectionsConfig(
        "yura.llm-connections.v1",
        "yura.llm-connections",
        1,
        tuple(LLMConnectionConfig(identifier, "test", {}) for identifier in ids),
    )


def test_connects_each_registered_connection_and_closes_once() -> None:
    async def run() -> None:
        events: list[str] = []
        registry = await create_llm_connection_registry(
            configuration("first", "second"), (), (Adapter("test", events),)
        )

        assert isinstance(registry.port("first"), Port)
        with pytest.raises(CoreConfigurationError):
            registry.port("missing")
        await asyncio.gather(registry.close(), registry.close())
        assert events == ["connect:first", "connect:second", "close:second", "close:first"]

    asyncio.run(run())


def test_failure_closes_already_created_connections_in_reverse_order() -> None:
    async def run() -> None:
        events: list[str] = []
        with pytest.raises(RuntimeError, match="接続失敗"):
            await create_llm_connection_registry(
                configuration("first", "second"), (), (Adapter("test", events, "second"),)
            )
        assert events == ["connect:first", "connect:second", "close:first"]

    asyncio.run(run())


def test_cleanup_failure_is_typed_without_hiding_an_unclosed_connection() -> None:
    async def run() -> None:
        events: list[str] = []
        with pytest.raises(CoreConfigurationError):
            await create_llm_connection_registry(
                configuration("first", "second"),
                (),
                (Adapter("test", events, "second", True),),
            )
        assert events == ["connect:first", "connect:second", "close:first"]

    asyncio.run(run())


def test_run_identity_has_no_git_head() -> None:
    identity = CoreRunIdentity("epoch", "run")

    assert identity.runtime_epoch == "epoch"
    assert identity.system_run_id == "run"
