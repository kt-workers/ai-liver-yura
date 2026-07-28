from __future__ import annotations

from types import SimpleNamespace

from app.core.plugins import (
    PluginLoader,
    PluginLoadStatus,
    PluginModuleSpec,
)


class StubPlugin:
    plugin_id = "stub"
    display_name = "Stub"
    capabilities = frozenset({"stub.capability"})

    def available_capabilities(self) -> frozenset[str]:
        return self.capabilities

    def initialize(self, context: object) -> None:
        return None

    def shutdown(self) -> None:
        return None


class StubFactory:
    def __init__(self) -> None:
        self.last_context = None

    def create_plugin(self, context: object) -> StubPlugin:
        self.last_context = context
        return StubPlugin()


def test_loader_does_not_import_disabled_plugin(monkeypatch) -> None:
    imported: list[str] = []

    def import_module(name: str) -> object:
        imported.append(name)
        raise AssertionError("disabled plugin must not be imported")

    monkeypatch.setattr("app.core.plugins.plugin_loader.importlib.import_module", import_module)

    results = PluginLoader().load(
        [PluginModuleSpec("missing", "missing.plugin", enabled=False)]
    )

    assert imported == []
    assert results[0].status is PluginLoadStatus.DISABLED
    assert results[0].plugin is None


def test_loader_creates_enabled_plugin_with_factory_context(monkeypatch) -> None:
    factory = StubFactory()
    module = SimpleNamespace(__name__="stub.module", plugin_factory=factory)
    monkeypatch.setattr(
        "app.core.plugins.plugin_loader.importlib.import_module", lambda _: module
    )

    results = PluginLoader(services={"clock": "service"}).load(
        [
            PluginModuleSpec(
                "stub",
                "stub.module",
                configuration={"enabled": True},
            )
        ]
    )

    assert results[0].status is PluginLoadStatus.LOADED
    assert isinstance(results[0].plugin, StubPlugin)
    assert factory.last_context.configuration == {"enabled": True}
    assert factory.last_context.services == {"clock": "service"}


def test_loader_isolates_import_failure_and_continues(monkeypatch) -> None:
    factory = StubFactory()
    healthy_module = SimpleNamespace(__name__="healthy.module", plugin_factory=factory)

    def import_module(name: str) -> object:
        if name == "broken.module":
            raise ModuleNotFoundError(name)
        return healthy_module

    monkeypatch.setattr("app.core.plugins.plugin_loader.importlib.import_module", import_module)

    results = PluginLoader().load(
        [
            PluginModuleSpec("broken", "broken.module"),
            PluginModuleSpec("stub", "healthy.module"),
        ]
    )

    assert results[0].status is PluginLoadStatus.FAILED
    assert results[0].error_type == "ModuleNotFoundError"
    assert results[1].status is PluginLoadStatus.LOADED


def test_loader_rejects_factory_returning_different_plugin_id(monkeypatch) -> None:
    module = SimpleNamespace(__name__="stub.module", plugin_factory=StubFactory())
    monkeypatch.setattr(
        "app.core.plugins.plugin_loader.importlib.import_module", lambda _: module
    )

    result = PluginLoader().load(
        [PluginModuleSpec("expected", "stub.module")]
    )[0]

    assert result.status is PluginLoadStatus.FAILED
    assert result.error_type == "ValueError"
