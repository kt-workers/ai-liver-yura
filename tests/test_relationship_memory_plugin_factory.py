from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.core.plugins import PluginContext, PluginManager, SystemClock
from app.domain.activities import Activity
from app.domain.relationships import RelationshipMemory
from app.plugins.relationship_memory import (
    RelationshipMemoryPlugin,
    RelationshipMemoryPluginFactory,
    plugin_factory,
)
from app.shared.contracts.plugins.factory import PluginFactoryContext


class _Store:
    def __init__(self, *, fail_load: bool = False) -> None:
        self.memory = RelationshipMemory()
        self.fail_load = fail_load
        self.saved: list[RelationshipMemory] = []

    def load(self) -> RelationshipMemory:
        if self.fail_load:
            raise OSError("store offline")
        return self.memory

    def save(self, memory: RelationshipMemory) -> None:
        self.memory = memory
        self.saved.append(memory)


class _ActivityGateway:
    def register(self, activity: Activity) -> Activity:
        return activity


class _LlmGateway:
    async def generate_response(self, activity: Activity) -> str:
        return ""


def _initialize(
    plugin: RelationshipMemoryPlugin[RelationshipMemory],
) -> PluginManager:
    manager = PluginManager()
    manager.register(plugin)
    manager.initialize_enabled_plugins(
        PluginContext(
            llm_gateway=_LlmGateway(),
            activity_gateway=_ActivityGateway(),
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
            services={"relationship_memory_store": store},
        )
    )
    manager = _initialize(plugin)
    memory = RelationshipMemory(max_entries=12)

    plugin.save(memory)

    assert plugin.load() is memory
    assert store.saved == [memory]
    assert manager.is_capability_available("memory.relationship", plugin.plugin_id)


def test_factory_allows_missing_store_and_initializes_degraded() -> None:
    plugin = RelationshipMemoryPluginFactory().create_plugin(
        PluginFactoryContext(
            configuration={},
            services={"relationship_memory_store": None},
        )
    )
    manager = _initialize(plugin)

    assert manager.get_plugin(plugin.plugin_id) is plugin
    assert plugin.available_capabilities() == frozenset()


@pytest.mark.parametrize(
    ("store", "message"),
    [
        (
            type("_MissingLoad", (), {"save": lambda self, memory: None})(),
            "relationship_memory.store must implement load()",
        ),
        (
            type("_MissingSave", (), {"load": lambda self: RelationshipMemory()})(),
            "relationship_memory.store must implement save()",
        ),
    ],
)
def test_factory_rejects_invalid_store(store: object, message: str) -> None:
    with pytest.raises(TypeError, match=message.replace("(", r"\(").replace(")", r"\)")):
        RelationshipMemoryPluginFactory().create_plugin(
            PluginFactoryContext(
                configuration={},
                services={"relationship_memory_store": store},
            )
        )


def test_factory_created_plugin_revokes_capability_on_load_failure() -> None:
    plugin = RelationshipMemoryPluginFactory().create_plugin(
        PluginFactoryContext(
            configuration={},
            services={"relationship_memory_store": _Store(fail_load=True)},
        )
    )
    manager = _initialize(plugin)

    with pytest.raises(OSError, match="store offline"):
        plugin.load()

    assert not manager.is_capability_available("memory.relationship", plugin.plugin_id)


def test_factory_does_not_import_concrete_storage_adapters() -> None:
    path = Path(__file__).parents[1] / "app/plugins/relationship_memory/factory.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert all(not name.startswith("app.adapters.storage") for name in imports)
