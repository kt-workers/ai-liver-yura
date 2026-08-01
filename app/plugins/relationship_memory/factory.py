from __future__ import annotations

from typing import Any

from app.plugins.relationship_memory.plugin import RelationshipMemoryPlugin
from app.shared.contracts.plugins.factory import PluginFactoryContext


class RelationshipMemoryPluginFactory:
    """共有Store契約からRelationship Memory Pluginを生成するFactory。"""

    def create_plugin(
        self,
        context: PluginFactoryContext,
    ) -> RelationshipMemoryPlugin[Any]:
        store = context.services.get("relationship_memory_store")
        self._validate_store(store)
        return RelationshipMemoryPlugin(store)

    @staticmethod
    def _validate_store(store: Any) -> None:
        if store is None:
            return
        if not callable(getattr(store, "load", None)):
            raise TypeError("relationship_memory.store must implement load()")
        if not callable(getattr(store, "save", None)):
            raise TypeError("relationship_memory.store must implement save()")


plugin_factory = RelationshipMemoryPluginFactory()
