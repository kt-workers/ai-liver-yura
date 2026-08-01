import pytest

from app.config.service_schema import (
    OpenAiServiceSettings,
    PostgresServiceSettings,
    VoiceVoxServiceSettings,
)
from app.config.typed_service_settings import as_database_service, as_http_ai_service


def test_http_ai_service_requires_connection_fields() -> None:
    typed = as_http_ai_service(
        OpenAiServiceSettings("https://api.example.com/v1", "API_KEY", 30.0),
        service_name="openai",
        allowed_types=("openai",),
    )
    assert typed.api_key_env == "API_KEY"


def test_http_ai_service_rejects_unexpected_type() -> None:
    with pytest.raises(RuntimeError, match="openai"):
        as_http_ai_service(
            VoiceVoxServiceSettings("http://localhost:50021", 30.0),
            service_name="llm",
            allowed_types=("openai",),
        )


def test_database_service_requires_postgres() -> None:
    assert as_database_service(
        PostgresServiceSettings("DATABASE_URL"),
        service_name="database",
    ).dsn_env == "DATABASE_URL"
