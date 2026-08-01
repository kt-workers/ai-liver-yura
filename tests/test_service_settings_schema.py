import pytest

from app.config.app_config import _load_services
from app.config.errors import ConfigError
from app.config.service_schema import (
    OllamaServiceSettings,
    OpenAiServiceSettings,
    PostgresServiceSettings,
    VoiceVoxServiceSettings,
)


@pytest.mark.parametrize(
    ("name", "raw", "expected"),
    [
        (
            "openai",
            {
                "type": "openai",
                "base_url": "https://api.example.com/v1",
                "api_key_env": "OPENAI_API_KEY",
                "timeout_seconds": 30.0,
            },
            OpenAiServiceSettings,
        ),
        (
            "ollama",
            {"type": "ollama", "base_url": "http://localhost", "timeout_seconds": 30},
            OllamaServiceSettings,
        ),
        (
            "voicevox",
            {"type": "voicevox", "base_url": "http://localhost", "timeout_seconds": 30},
            VoiceVoxServiceSettings,
        ),
        ("database", {"type": "postgres", "dsn_env": "DATABASE_URL"}, PostgresServiceSettings),
    ],
)
def test_core_service_types_are_parsed(name, raw, expected) -> None:
    assert isinstance(_load_services({name: raw})[name], expected)


@pytest.mark.parametrize("service_type", ["youtube", "google_youtube", "obs_websocket", "fake"])
def test_streaming_concrete_service_types_are_rejected(service_type: str) -> None:
    with pytest.raises(ConfigError, match="unknown service type"):
        _load_services({"legacy": {"type": service_type}})
