from __future__ import annotations

from app.config.app_config import AppConfig, ServiceSettings
from app.config.typed_service_settings import (
    DatabaseServiceSettings,
    HttpAiServiceSettings,
    ResolvedObsServiceSettings,
    ResolvedYouTubeServiceSettings,
    as_database_service,
    as_http_ai_service,
    as_obs_websocket_service,
    as_youtube_service,
)


def resolve_service(config: AppConfig, service_name: str) -> ServiceSettings:
    """Composition Rootで名前付きサービス設定を解決する。"""

    try:
        return config.services[service_name]
    except KeyError as error:
        raise RuntimeError(f"未定義のサービスです: {service_name}") from error


def resolve_http_ai_service(
    config: AppConfig,
    service_name: str,
    *,
    allowed_types: tuple[str, ...] = ("openai", "ollama", "voicevox"),
) -> HttpAiServiceSettings:
    return as_http_ai_service(
        resolve_service(config, service_name),
        service_name=service_name,
        allowed_types=allowed_types,
    )


def resolve_database_service(
    config: AppConfig,
    service_name: str,
) -> DatabaseServiceSettings:
    return as_database_service(
        resolve_service(config, service_name),
        service_name=service_name,
    )


def resolve_youtube_service(
    config: AppConfig,
    service_name: str = "youtube",
) -> ResolvedYouTubeServiceSettings:
    return as_youtube_service(
        resolve_service(config, service_name),
        service_name=service_name,
    )


def resolve_obs_service(
    config: AppConfig,
    service_name: str = "obs",
) -> ResolvedObsServiceSettings:
    return as_obs_websocket_service(
        resolve_service(config, service_name),
        service_name=service_name,
    )
