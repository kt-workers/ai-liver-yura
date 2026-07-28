from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from typing import Any

from app.core.plugins import PluginLoader, PluginLoadStatus, PluginModuleSpec
from app.shared.contracts.plugins.runtime import Plugin


def load_plugin_from_factory(
    *,
    plugin_id: str,
    module: str,
    enabled: bool,
    configuration: object | None = None,
    services: Mapping[str, Any] | None = None,
) -> Plugin | None:
    """有効なPluginだけをFactory経由でロードする。

    無効なPluginはimportしない。ロード失敗は呼び出し側がCoreの縮退動作を
    選べるよう、Plugin単位のRuntimeErrorとして通知する。
    """

    normalized_configuration = _normalize_configuration(configuration)
    result = PluginLoader(services=services).load(
        (
            PluginModuleSpec(
                plugin_id=plugin_id,
                module=module,
                enabled=enabled,
                configuration=normalized_configuration,
            ),
        )
    )[0]

    if result.status is PluginLoadStatus.DISABLED:
        return None
    if result.status is PluginLoadStatus.FAILED:
        raise RuntimeError(
            f"Pluginのロードに失敗しました: {plugin_id} "
            f"({result.error_type}: {result.error_message})"
        )
    if result.plugin is None:
        raise RuntimeError(f"Plugin FactoryがPluginを返しませんでした: {plugin_id}")
    return result.plugin


def _normalize_configuration(configuration: object | None) -> Mapping[str, Any]:
    if configuration is None:
        return {}
    if is_dataclass(configuration) and not isinstance(configuration, type):
        return asdict(configuration)
    if isinstance(configuration, Mapping):
        return dict(configuration)
    raise TypeError("Plugin設定はdataclassまたはMappingである必要があります。")
