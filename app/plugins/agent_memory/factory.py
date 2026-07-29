from __future__ import annotations

from typing import Any

from app.plugins.agent_memory.plugin import AgentMemoryPlugin
from app.shared.contracts.plugins.factory import PluginFactoryContext


class AgentMemoryPluginFactory:
    """共有Store契約からAgent Memory Pluginを生成するFactory。"""

    def create_plugin(
        self,
        context: PluginFactoryContext,
    ) -> AgentMemoryPlugin:
        store = context.services.get("agent_memory_store")
        self._validate_store(store)
        return AgentMemoryPlugin(store)

    @staticmethod
    def _validate_store(store: Any) -> None:
        if store is None:
            return
        if not callable(getattr(store, "load", None)):
            raise TypeError("agent_memory.store must implement load()")
        if not callable(getattr(store, "save", None)):
            raise TypeError("agent_memory.store must implement save()")


plugin_factory = AgentMemoryPluginFactory()
