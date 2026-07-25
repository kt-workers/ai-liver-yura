from __future__ import annotations

from dataclasses import dataclass

from app.bootstrap.service_settings import resolve_http_ai_service
from app.config.app_config import AppConfig, ModelSettings
from app.config.typed_service_settings import HttpAiServiceSettings


@dataclass(frozen=True, slots=True)
class ResolvedAiModelSettings:
    """モデル定義と、そのモデルが利用するHTTP AIサービス設定。"""

    key: str
    model: ModelSettings
    service: HttpAiServiceSettings


def resolve_ai_model(
    config: AppConfig,
    model_key: str,
    *,
    allowed_service_types: tuple[str, ...] = ("openai", "ollama", "voicevox"),
) -> ResolvedAiModelSettings:
    """モデルキーからモデル定義と型付きサービス設定を解決する。"""

    try:
        model = config.models[model_key]
    except KeyError as error:
        raise RuntimeError(f"未定義のモデルです: {model_key}") from error

    service = resolve_http_ai_service(
        config,
        model.service,
        allowed_types=allowed_service_types,
    )
    return ResolvedAiModelSettings(
        key=model_key,
        model=model,
        service=service,
    )


def require_embedding_dimension(resolved: ResolvedAiModelSettings) -> int:
    """埋め込みモデルに必須の次元数を返す。"""

    dimension = resolved.model.dimension
    if dimension is None or dimension <= 0:
        raise RuntimeError(f"models.{resolved.key}.dimension が必要です。")
    return dimension
