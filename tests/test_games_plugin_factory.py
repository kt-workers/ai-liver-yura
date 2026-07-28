from __future__ import annotations

import pytest

from app.plugins.games import GamesPlugin
from app.plugins.games.factory import plugin_factory
from app.plugins.games.settings import GamesPluginSettings
from app.shared.contracts.plugins.factory import PluginFactoryContext


def test_games_plugin_factory_creates_games_plugin() -> None:
    settings = GamesPluginSettings()

    plugin = plugin_factory.create_plugin(
        PluginFactoryContext(
            configuration={"settings": settings},
            services={},
        )
    )

    assert isinstance(plugin, GamesPlugin)
    assert plugin.plugin_id == "games"


def test_games_plugin_factory_rejects_invalid_settings() -> None:
    with pytest.raises(TypeError, match="games.settings"):
        plugin_factory.create_plugin(
            PluginFactoryContext(
                configuration={"settings": object()},
                services={},
            )
        )
