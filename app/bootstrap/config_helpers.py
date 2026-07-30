from __future__ import annotations

from app.config.app_config import AppConfig, ServiceSettings
from app.config.service_schema import (
    OllamaServiceSettings,
    OpenAiServiceSettings,
    VoiceVoxServiceSettings,
)


def resolve_service(config: AppConfig, key: str) -> ServiceSettings:
    try:
        return config.services[key]
    except KeyError as error:
        raise RuntimeError(f"未定義のサービスです: {key}") from error


def require_service_value(value: str | None, field: str, service: str) -> str:
    if value is None:
        raise RuntimeError(f"services.{service}.{field} が必要です。")
    return value


def service_timeout(service: ServiceSettings) -> float:
    if isinstance(
        service,
        (OpenAiServiceSettings, OllamaServiceSettings, VoiceVoxServiceSettings),
    ):
        return service.timeout_seconds
    raise RuntimeError("外部AIサービスには timeout_seconds が必要です。")
