from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.bootstrap.plugin_factory_loader import load_plugin_from_factory
from app.core.plugins import PluginManager
from app.shared.contracts.plugins.runtime import Plugin


def register_optional_plugin_from_factory(
    manager: PluginManager,
    *,
    plugin_id: str,
    module: str,
    enabled: bool,
    configuration: object | None = None,
    services: Mapping[str, Any] | None = None,
) -> Plugin | None:
    """有効なPluginだけをFactory経由で生成し、Plugin Managerへ登録する。"""

    plugin = load_plugin_from_factory(
        plugin_id=plugin_id,
        module=module,
        enabled=enabled,
        configuration=configuration,
        services=services,
    )
    if plugin is None:
        return None
    manager.register(plugin)
    return plugin
