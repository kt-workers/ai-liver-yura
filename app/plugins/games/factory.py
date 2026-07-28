from __future__ import annotations

from app.plugins.games.plugin import GamesPlugin
from app.plugins.games.settings import GamesPluginSettings
from app.shared.contracts.plugins.factory import PluginFactoryContext


class GamesPluginFactory:
    """Games Pluginの具象生成をPluginパッケージ内に閉じ込めるFactory。"""

    def create_plugin(self, context: PluginFactoryContext) -> GamesPlugin:
        settings = context.configuration.get("settings")
        if settings is not None and not isinstance(settings, GamesPluginSettings):
            raise TypeError("games.settings must be GamesPluginSettings")
        return GamesPlugin(settings)


plugin_factory = GamesPluginFactory()
