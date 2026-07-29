from __future__ import annotations

from typing import Any

from app.plugins.voice_output.plugin import VoiceOutputPlugin
from app.shared.contracts.plugins.factory import PluginFactoryContext


class VoiceOutputPluginFactory:
    """Voice Output Pluginの具象生成をPluginパッケージ内に閉じ込めるFactory。"""

    def create_plugin(self, context: PluginFactoryContext) -> VoiceOutputPlugin:
        synthesizer = context.services.get("speech_synthesizer")
        player = context.services.get("audio_player")

        self._validate_service(
            synthesizer,
            method_name="synthesize",
            service_name="voice_output.speech_synthesizer",
        )
        self._validate_service(
            player,
            method_name="play",
            service_name="voice_output.audio_player",
        )
        return VoiceOutputPlugin(synthesizer, player)

    @staticmethod
    def _validate_service(
        service: Any,
        *,
        method_name: str,
        service_name: str,
    ) -> None:
        if service is None:
            return
        if not callable(getattr(service, method_name, None)):
            raise TypeError(f"{service_name} must implement {method_name}()")


plugin_factory = VoiceOutputPluginFactory()
