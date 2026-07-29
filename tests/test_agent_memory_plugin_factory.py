from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.core.plugins import PluginContext, PluginManager, SystemClock
from app.plugins.agent_memory import (
    AgentMemoryPlugin,
    AgentMemoryPluginFactory,
    plugin_factory,
)
from app.shared.contracts.memory import AgentMemorySnapshot
from app.shared.contracts.plugins.factory import PluginFactoryContext


class _Store:
    def __init__(self, *, fail_load: bool = False) -> None:
        self.snapshot = AgentMemorySnapshot()
        self.fail_load = fail_load
        self.saved: list[AgentMemorySnapshot] = []

    def load(self) -> AgentMemorySnapshot:
        if self.fail_load:
            raise OSError("store offline")
        return self.snapshot

    def save(self, snapshot: AgentMemorySnapshot) -> None:
        self.snapshot = snapshot
        self.saved.append(snapshot)


class _Gateway:
    async def generate_response(self, request: object) -> str:
        return ""

    def register(self, activity: object) -> object:
        return activity


def _initialize(plugin: AgentMemoryPlugin) -> PluginManager:
    manager = PluginManager()
    manager.register(plugin)
    gateway = _Gateway()
    manager.initialize_enabled_plugins(
        PluginContext(
            llm_gateway=gateway,
            activity_gateway=gateway,
            clock=SystemClock(),
            configuration={},
            capability_reporter=manager,
        ),
        {plugin.plugin_id: True},
    )
    return manager


def test_factory_creates_plugin_that_delegates_to_shared_store() -> None:
    store = _Store()
    plugin = plugin_factory.create_plugin(
        PluginFactoryContext(
            configuration={},
            services={"agent_memory_store": store},
        )
    )
    manager = _initialize(plugin)
    snapshot = AgentMemorySnapshot()

    plugin.save(snapshot)

    assert plugin.load() is snapshot
    assert store.saved == [snapshot]
    assert manager.is_capability_available("memory.agent_state", plugin.plugin_id)


def test_factory_allows_missing_store_and_initializes_degraded() -> None:
    plugin = AgentMemoryPluginFactory().create_plugin(
        PluginFactoryContext(
            configuration={},
            services={"agent_memory_store": None},
        )
    )
    manager = _initialize(plugin)

    assert manager.get_plugin(plugin.plugin_id) is plugin
    assert plugin.available_capabilities() == frozenset()


@pytest.mark.parametrize(
    ("store", "message"),
    [
        (
            type("_MissingLoad", (), {"save": lambda self, snapshot: None})(),
            "agent_memory.store must implement load()",
        ),
        (
            type("_MissingSave", (), {"load": lambda self: AgentMemorySnapshot()})(),
            "agent_memory.store must implement save()",
        ),
    ],
)
def test_factory_rejects_invalid_store(store: object, message: str) -> None:
    with pytest.raises(TypeError, match=message.replace("(", r"\(").replace(")", r"\)")):
        AgentMemoryPluginFactory().create_plugin(
            PluginFactoryContext(
                configuration={},
                services={"agent_memory_store": store},
            )
        )


def test_factory_created_plugin_revokes_capability_on_store_failure() -> None:
    plugin = AgentMemoryPluginFactory().create_plugin(
        PluginFactoryContext(
            configuration={},
            services={"agent_memory_store": _Store(fail_load=True)},
        )
    )
    manager = _initialize(plugin)

    with pytest.raises(OSError, match="store offline"):
        plugin.load()

    assert not manager.is_capability_available("memory.agent_state", plugin.plugin_id)


def test_factory_does_not_import_concrete_storage_adapters() -> None:
    path = Path(__file__).parents[1] / "app/plugins/agent_memory/factory.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert all(not name.startswith("app.adapters.storage") for name in imports)
