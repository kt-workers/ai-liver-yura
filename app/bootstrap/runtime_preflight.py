from __future__ import annotations

from app.bootstrap.adapter_settings import (
    resolve_llm_adapter_settings,
    resolve_topic_memory_store_settings,
)
from app.bootstrap.service_settings import resolve_http_ai_service
from app.config.app_config import AppConfig


def validate_runtime_service_settings(config: AppConfig) -> None:
    """標準Runtimeが実際に利用する外部サービス設定を起動前に検証する。"""

    if config.response_generator.type == "llm":
        resolve_llm_adapter_settings(config, config.response_generator.model)

    if config.speech.enabled:
        resolve_http_ai_service(
            config,
            config.speech.service,
            allowed_types=("voicevox",),
        )

    if config.response_generator.type != "dummy":
        resolve_llm_adapter_settings(config, config.topic_classifier.model)

    if config.memory.topic_memory.enabled:
        resolve_llm_adapter_settings(
            config,
            config.memory.topic_memory.embedding_model,
        )
        resolve_topic_memory_store_settings(config)
