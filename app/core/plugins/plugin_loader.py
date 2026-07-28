from __future__ import annotations

import importlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from types import ModuleType
from typing import Any

from app.shared.contracts.plugins.factory import PluginFactory, PluginFactoryContext
from app.shared.contracts.plugins.runtime.plugin import Plugin


class PluginLoadStatus(str, Enum):
    LOADED = "loaded"
    DISABLED = "disabled"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class PluginModuleSpec:
    plugin_id: str
    module: str
    enabled: bool = True
    factory_attribute: str = "plugin_factory"
    configuration: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class PluginLoadResult:
    plugin_id: str
    module: str
    status: PluginLoadStatus
    plugin: Plugin | None = None
    error_type: str | None = None
    error_message: str | None = None


class PluginLoader:
    """有効なPluginだけを動的importし、失敗をPlugin単位で隔離する。"""

    def __init__(self, services: Mapping[str, Any] | None = None) -> None:
        self._services = dict(services or {})

    def load(self, specs: Iterable[PluginModuleSpec]) -> tuple[PluginLoadResult, ...]:
        return tuple(self._load_one(spec) for spec in specs)

    def _load_one(self, spec: PluginModuleSpec) -> PluginLoadResult:
        if not spec.enabled:
            return PluginLoadResult(
                plugin_id=spec.plugin_id,
                module=spec.module,
                status=PluginLoadStatus.DISABLED,
            )

        try:
            module = importlib.import_module(spec.module)
            factory = self._factory_from(module, spec.factory_attribute)
            plugin = factory.create_plugin(
                PluginFactoryContext(
                    configuration=dict(spec.configuration or {}),
                    services=self._services,
                )
            )
            if plugin.plugin_id != spec.plugin_id:
                raise ValueError(
                    "Plugin Factoryが異なるplugin_idを返しました: "
                    f"expected={spec.plugin_id} actual={plugin.plugin_id}"
                )
            return PluginLoadResult(
                plugin_id=spec.plugin_id,
                module=spec.module,
                status=PluginLoadStatus.LOADED,
                plugin=plugin,
            )
        except Exception as error:  # Plugin境界でimport・生成失敗を隔離する。
            return PluginLoadResult(
                plugin_id=spec.plugin_id,
                module=spec.module,
                status=PluginLoadStatus.FAILED,
                error_type=type(error).__name__,
                error_message=str(error),
            )

    @staticmethod
    def _factory_from(module: ModuleType, attribute: str) -> PluginFactory:
        factory = getattr(module, attribute, None)
        if factory is None or not callable(getattr(factory, "create_plugin", None)):
            raise TypeError(
                f"Plugin Factoryが見つかりません: {module.__name__}.{attribute}"
            )
        return factory
