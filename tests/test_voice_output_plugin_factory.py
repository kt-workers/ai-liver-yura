from __future__ import annotations

import pytest

from app.plugins.voice_output import VoiceOutputPlugin, VoiceOutputPluginFactory
from app.shared.contracts.plugins.factory import PluginFactoryContext


class FakeSynthesizer:
    async def synthesize(self, text: str, voice_intent: object | None = None) -> bytes:
        return text.encode("utf-8")


class FakePlayer:
    async def play(self, audio_data: bytes) -> None:
        return None


def test_voice_output_plugin_factory_creates_plugin_from_shared_services() -> None:
    plugin = VoiceOutputPluginFactory().create_plugin(
        PluginFactoryContext(
            configuration={},
            services={
                "speech_synthesizer": FakeSynthesizer(),
                "audio_player": FakePlayer(),
            },
        )
    )

    assert isinstance(plugin, VoiceOutputPlugin)
    assert plugin.plugin_id == "voice_output"


def test_voice_output_plugin_factory_allows_degraded_services() -> None:
    plugin = VoiceOutputPluginFactory().create_plugin(
        PluginFactoryContext(
            configuration={},
            services={
                "speech_synthesizer": None,
                "audio_player": FakePlayer(),
            },
        )
    )

    assert isinstance(plugin, VoiceOutputPlugin)


@pytest.mark.parametrize(
    ("services", "expected_message"),
    [
        (
            {"speech_synthesizer": object(), "audio_player": FakePlayer()},
            "voice_output.speech_synthesizer must implement synthesize()",
        ),
        (
            {"speech_synthesizer": FakeSynthesizer(), "audio_player": object()},
            "voice_output.audio_player must implement play()",
        ),
    ],
)
def test_voice_output_plugin_factory_rejects_invalid_services(
    services: dict[str, object],
    expected_message: str,
) -> None:
    with pytest.raises(TypeError, match=expected_message.replace("(", r"\(").replace(")", r"\)")):
        VoiceOutputPluginFactory().create_plugin(
            PluginFactoryContext(configuration={}, services=services)
        )
