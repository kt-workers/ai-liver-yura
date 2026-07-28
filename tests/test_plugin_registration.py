from __future__ import annotations

from app.bootstrap.plugin_registration import register_optional_plugin_from_factory
from app.core.plugins import PluginManager


class _Plugin:
    plugin_id = "games"
    display_name = "Games"
    capabilities = frozenset()

    def available_capabilities(self) -> frozenset[str]:
        return frozenset()

    def initialize(self, context: object) -> None:
        return None

    def shutdown(self) -> None:
        return None


def test_disabled_plugin_is_not_registered(monkeypatch) -> None:
    manager = PluginManager()

    def load_plugin_from_factory(**kwargs: object) -> None:
        assert kwargs["enabled"] is False
        return None

    monkeypatch.setattr(
        "app.bootstrap.plugin_registration.load_plugin_from_factory",
        load_plugin_from_factory,
    )

    result = register_optional_plugin_from_factory(
        manager,
        plugin_id="games",
        module="app.plugins.games",
        enabled=False,
    )

    assert result is None
    assert manager.list_plugins() == []


def test_enabled_plugin_is_registered(monkeypatch) -> None:
    manager = PluginManager()
    plugin = _Plugin()
    monkeypatch.setattr(
        "app.bootstrap.plugin_registration.load_plugin_from_factory",
        lambda **_: plugin,
    )

    result = register_optional_plugin_from_factory(
        manager,
        plugin_id="games",
        module="app.plugins.games",
        enabled=True,
        configuration={"enabled": True},
    )

    assert result is plugin
    assert manager.list_plugins() == [plugin]
