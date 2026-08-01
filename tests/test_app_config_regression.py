from __future__ import annotations

import pytest

from app.config.app_config import load_app_config
from app.config.service_schema import OpenAiServiceSettings, VoiceVoxServiceSettings


def test_current_config_yaml_loads_successfully() -> None:
    config = load_app_config()
    assert config.app.mode == "console"
    assert config.trace.level == "INFO"
    assert isinstance(config.services["openai"], OpenAiServiceSettings)
    assert isinstance(config.services["voicevox"], VoiceVoxServiceSettings)
    assert config.models["openai_chat"].name == "gpt-4.1-mini"
    assert config.speech.speaker_id == 89
    assert config.memory.topic_memory.enabled is True
    assert not hasattr(config, "streaming")
    assert not hasattr(config.plugins, "games")


def test_loaded_configuration_collections_are_immutable() -> None:
    config = load_app_config()
    with pytest.raises(TypeError):
        config.services["new"] = config.services["openai"]  # type: ignore[index]
    assert isinstance(config.character.likes, tuple)
    assert isinstance(config.speech.voice_intent_profiles, type(config.services))
