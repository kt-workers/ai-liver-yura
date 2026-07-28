from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from app.shared.contracts.plugins.runtime.plugin import Plugin


@dataclass(frozen=True, slots=True)
class PluginFactoryContext:
    """Plugin具象を構築するために外側から渡す読み取り専用情報。"""

    configuration: Mapping[str, Any]
    services: Mapping[str, Any]


class PluginFactory(Protocol):
    """Pluginパッケージが公開する具象生成契約。"""

    def create_plugin(self, context: PluginFactoryContext) -> Plugin: ...
