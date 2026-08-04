from __future__ import annotations

from typing import Any

from app.plugins.avatar_output.plugin import AvatarOutputPlugin
from app.shared.contracts.plugins.factory import PluginFactoryContext


class AvatarOutputPluginFactory:
    """Avatar Output Pluginの具象生成をPluginパッケージ内へ閉じ込める。"""

    def create_plugin(self, context: PluginFactoryContext) -> AvatarOutputPlugin:
        adapter = context.services.get("avatar_output")
        self._validate_adapter(adapter)
        return AvatarOutputPlugin(adapter)

    @staticmethod
    def _validate_adapter(adapter: Any) -> None:
        if adapter is None:
            return
        # Performance送信は段階移行中の任意Capability。
        # 既存Adapterは個別Actionの契約を満たせば引き続き利用できる。
        for method_name in (
            "set_expression",
            "play_gesture",
            "set_gaze",
        ):
            if not callable(getattr(adapter, method_name, None)):
                raise TypeError(
                    f"avatar_output must implement {method_name}()"
                )


plugin_factory = AvatarOutputPluginFactory()
