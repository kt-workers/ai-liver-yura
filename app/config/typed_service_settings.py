from __future__ import annotations

from typing import TypeAlias

from app.config.service_schema import (
    FakeObsServiceSettings,
    FakeYouTubeServiceSettings,
    HttpAiServiceSettings,
    ObsWebSocketServiceSettings,
    OllamaServiceSettings,
    OpenAiServiceSettings,
    PostgresServiceSettings,
    ServiceSettings,
    VoiceVoxServiceSettings,
    YouTubeServiceSettings,
)

DatabaseServiceSettings: TypeAlias = PostgresServiceSettings
ResolvedYouTubeServiceSettings: TypeAlias = (
    YouTubeServiceSettings | FakeYouTubeServiceSettings
)
ResolvedObsServiceSettings: TypeAlias = (
    ObsWebSocketServiceSettings | FakeObsServiceSettings
)

__all__ = [
    "DatabaseServiceSettings",
    "HttpAiServiceSettings",
    "ObsWebSocketServiceSettings",
    "ResolvedObsServiceSettings",
    "ResolvedYouTubeServiceSettings",
    "YouTubeServiceSettings",
    "as_database_service",
    "as_http_ai_service",
    "as_obs_websocket_service",
    "as_youtube_service",
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


def as_youtube_service(
    service: ServiceSettings,
    *,
    service_name: str = "youtube",
) -> ResolvedYouTubeServiceSettings:
    if not isinstance(service, (YouTubeServiceSettings, FakeYouTubeServiceSettings)):
        raise RuntimeError(
            f"services.{service_name}.type は youtube系または fake を指定してください。"
        )
    if service.request_timeout_seconds <= 0 or service.oauth_timeout_seconds <= 0:
        raise RuntimeError(f"services.{service_name}.timeout は正数です。")
    if service.max_retries < 0 or service.retry_initial_delay_seconds <= 0:
        raise RuntimeError(f"services.{service_name}.retry が不正です。")
    return service


def as_obs_websocket_service(
    service: ServiceSettings,
    *,
    service_name: str = "obs",
) -> ResolvedObsServiceSettings:
    if not isinstance(service, (ObsWebSocketServiceSettings, FakeObsServiceSettings)):
        raise RuntimeError(
            f"services.{service_name}.type は obs_websocket または fake を指定してください。"
        )
    if isinstance(service, ObsWebSocketServiceSettings):
        if not 1 <= service.port <= 65535:
            raise RuntimeError(
                f"services.{service_name}.port は1以上65535以下です。"
            )
        if (
            service.connect_timeout_seconds <= 0
            or service.request_timeout_seconds <= 0
            or service.retry_initial_delay_seconds <= 0
            or service.max_retries < 0
        ):
            raise RuntimeError(f"services.{service_name} のtimeout/retryが不正です。")
    return service
