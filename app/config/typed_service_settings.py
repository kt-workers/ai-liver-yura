from __future__ import annotations

from typing import TypeAlias

from app.config.service_schema import (
    HttpAiServiceSettings,
    OllamaServiceSettings,
    OpenAiServiceSettings,
    PostgresServiceSettings,
    ServiceSettings,
    VoiceVoxServiceSettings,
)

DatabaseServiceSettings: TypeAlias = PostgresServiceSettings

__all__ = [
    "DatabaseServiceSettings",
    "HttpAiServiceSettings",
    "as_database_service",
    "as_http_ai_service",
]


def as_http_ai_service(
    service: ServiceSettings,
    *,
    service_name: str,
    allowed_types: tuple[str, ...],
) -> HttpAiServiceSettings:
    if not isinstance(
        service,
        (OpenAiServiceSettings, OllamaServiceSettings, VoiceVoxServiceSettings),
    ) or service.type not in allowed_types:
        allowed = ", ".join(allowed_types)
        raise RuntimeError(
            f"services.{service_name}.type は {allowed} のいずれかを指定してください。"
        )
    if not isinstance(service.base_url, str) or not service.base_url.strip():
        raise RuntimeError(f"services.{service_name}.base_url が必要です。")
    if (
        isinstance(service.timeout_seconds, bool)
        or not isinstance(service.timeout_seconds, (int, float))
        or service.timeout_seconds <= 0
    ):
        raise RuntimeError(f"services.{service_name}.timeout_seconds は正数です。")
    if isinstance(service, OpenAiServiceSettings) and (
        not isinstance(service.api_key_env, str) or not service.api_key_env.strip()
    ):
        raise RuntimeError(f"services.{service_name}.api_key_env が必要です。")
    return service


def as_database_service(
    service: ServiceSettings,
    *,
    service_name: str,
) -> DatabaseServiceSettings:
    if not isinstance(service, PostgresServiceSettings):
        raise RuntimeError(
            f"services.{service_name}.type は postgres を指定してください。"
        )
    if not isinstance(service.dsn_env, str) or not service.dsn_env.strip():
        raise RuntimeError(f"services.{service_name}.dsn_env が必要です。")
    return service
