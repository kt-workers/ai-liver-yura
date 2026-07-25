from __future__ import annotations

from dataclasses import dataclass

from app.config.app_config import ServiceSettings


@dataclass(frozen=True, slots=True)
class HttpAiServiceSettings:
    type: str
    base_url: str
    timeout_seconds: float
    api_key_env: str | None = None


@dataclass(frozen=True, slots=True)
class DatabaseServiceSettings:
    type: str
    dsn_env: str


@dataclass(frozen=True, slots=True)
class YouTubeServiceSettings:
    type: str
    client_secret_path_env: str
    token_path_env: str
    request_timeout_seconds: float
    max_retries: int
    retry_initial_delay_seconds: float
    oauth_open_browser: bool
    allow_live_broadcast: bool
    oauth_timeout_seconds: float
    allowed_privacy_statuses: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ObsWebSocketServiceSettings:
    type: str
    host: str
    port: int
    password_env: str | None
    connect_timeout_seconds: float
    request_timeout_seconds: float
    max_retries: int
    retry_initial_delay_seconds: float


def as_http_ai_service(
    service: ServiceSettings,
    *,
    service_name: str,
    allowed_types: tuple[str, ...],
) -> HttpAiServiceSettings:
    if service.type not in allowed_types:
        allowed = ", ".join(allowed_types)
        raise RuntimeError(
            f"services.{service_name}.type は {allowed} のいずれかを指定してください。"
        )
    return HttpAiServiceSettings(
        type=service.type,
        base_url=_require(service.base_url, service_name, "base_url"),
        timeout_seconds=_require_positive(
            service.timeout_seconds, service_name, "timeout_seconds"
        ),
        api_key_env=service.api_key_env,
    )


def as_database_service(
    service: ServiceSettings,
    *,
    service_name: str,
) -> DatabaseServiceSettings:
    if service.type != "postgres":
        raise RuntimeError(
            f"services.{service_name}.type は postgres を指定してください。"
        )
    return DatabaseServiceSettings(
        type=service.type,
        dsn_env=_require(service.dsn_env, service_name, "dsn_env"),
    )


def as_youtube_service(
    service: ServiceSettings,
    *,
    service_name: str = "youtube",
) -> YouTubeServiceSettings:
    if service.type not in {"youtube_api", "fake"}:
        raise RuntimeError(
            f"services.{service_name}.type は youtube_api または fake を指定してください。"
        )
    return YouTubeServiceSettings(
        type=service.type,
        client_secret_path_env=_require(
            service.client_secret_path_env, service_name, "client_secret_path_env"
        ),
        token_path_env=_require(
            service.token_path_env, service_name, "token_path_env"
        ),
        request_timeout_seconds=_require_positive(
            service.request_timeout_seconds,
            service_name,
            "request_timeout_seconds",
        ),
        max_retries=_require_non_negative(
            service.max_retries, service_name, "max_retries"
        ),
        retry_initial_delay_seconds=_require_positive(
            service.retry_initial_delay_seconds,
            service_name,
            "retry_initial_delay_seconds",
        ),
        oauth_open_browser=(
            service.oauth_open_browser
            if service.oauth_open_browser is not None
            else True
        ),
        allow_live_broadcast=(
            service.allow_live_broadcast
            if service.allow_live_broadcast is not None
            else False
        ),
        oauth_timeout_seconds=_require_positive(
            service.oauth_timeout_seconds,
            service_name,
            "oauth_timeout_seconds",
        ),
        allowed_privacy_statuses=(
            service.allowed_privacy_statuses
            if service.allowed_privacy_statuses is not None
            else ("private", "unlisted", "public")
        ),
    )


def as_obs_websocket_service(
    service: ServiceSettings,
    *,
    service_name: str = "obs",
) -> ObsWebSocketServiceSettings:
    if service.type not in {"obs_websocket", "fake"}:
        raise RuntimeError(
            f"services.{service_name}.type は obs_websocket または fake を指定してください。"
        )
    return ObsWebSocketServiceSettings(
        type=service.type,
        host=_require(service.host, service_name, "host"),
        port=_require_port(service.port, service_name),
        password_env=service.password_env,
        connect_timeout_seconds=_require_positive(
            service.connect_timeout_seconds,
            service_name,
            "connect_timeout_seconds",
        ),
        request_timeout_seconds=_require_positive(
            service.request_timeout_seconds,
            service_name,
            "request_timeout_seconds",
        ),
        max_retries=_require_non_negative(
            service.max_retries, service_name, "max_retries"
        ),
        retry_initial_delay_seconds=_require_positive(
            service.retry_initial_delay_seconds,
            service_name,
            "retry_initial_delay_seconds",
        ),
    )


def _require(value: str | None, service_name: str, field_name: str) -> str:
    if value is None or not value.strip():
        raise RuntimeError(f"services.{service_name}.{field_name} が必要です。")
    return value


def _require_positive(
    value: float | None,
    service_name: str,
    field_name: str,
) -> float:
    if value is None or value <= 0:
        raise RuntimeError(f"services.{service_name}.{field_name} は正数です。")
    return value


def _require_non_negative(
    value: int | None,
    service_name: str,
    field_name: str,
) -> int:
    if value is None or value < 0:
        raise RuntimeError(f"services.{service_name}.{field_name} は0以上です。")
    return value


def _require_port(value: int | None, service_name: str) -> int:
    if value is None or not 1 <= value <= 65535:
        raise RuntimeError(f"services.{service_name}.port は1以上65535以下です。")
    return value
