from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.bootstrap.plugin_factory_loader import load_plugin_from_factory


class _Plugin:
    plugin_id = "sample"
    display_name = "Sample"
    capabilities = frozenset()

    def available_capabilities(self) -> frozenset[str]:
        return frozenset()

    def initialize(self, context: object) -> None:
        return None

    def shutdown(self) -> None:
        return None


class _Factory:
    def create_plugin(self, context: object) -> _Plugin:
        return _Plugin()


def test_disabled_plugin_is_not_imported(monkeypatch) -> None:
    def fail_import(name: str) -> object:
        raise AssertionError(f"無効Pluginをimportしました: {name}")

    monkeypatch.setattr(
        "app.core.plugins.plugin_loader.importlib.import_module",
        fail_import,
    )

    plugin = load_plugin_from_factory(
        plugin_id="sample",
        module="missing.sample",
        enabled=False,
    )

    assert plugin is None


def test_enabled_plugin_is_created_via_factory(monkeypatch) -> None:
    module = SimpleNamespace(__name__="sample.module", plugin_factory=_Factory())
    monkeypatch.setattr(
        "app.core.plugins.plugin_loader.importlib.import_module",
        lambda _: module,
    )

    plugin = load_plugin_from_factory(
        plugin_id="sample",
        module="sample.module",
        enabled=True,
        configuration={"enabled": True},
    )

    assert isinstance(plugin, _Plugin)


def test_plugin_load_failure_is_reported_as_runtime_error(monkeypatch) -> None:
    def fail_import(name: str) -> object:
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(
        "app.core.plugins.plugin_loader.importlib.import_module",
        fail_import,
    )

    with pytest.raises(RuntimeError, match="Pluginのロードに失敗しました"):
        load_plugin_from_factory(
            plugin_id="sample",
            module="missing.sample",
            enabled=True,
        )
