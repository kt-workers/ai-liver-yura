from __future__ import annotations

from dataclasses import replace

import pytest

from app.bootstrap.model_settings import (
    require_embedding_dimension,
    resolve_ai_model,
)
from app.config.app_config import ModelSettings, load_config


def test_resolve_ai_model_returns_model_and_typed_service() -> None:
    config = load_config()

    resolved = resolve_ai_model(config, "openai_chat")

    assert resolved.key == "openai_chat"
    assert resolved.model.name == "gpt-4.1-mini"
    assert resolved.service.type == "openai"
    assert resolved.service.base_url == "https://api.openai.com/v1"


def test_resolve_ai_model_rejects_unknown_model() -> None:
    config = load_config()

    with pytest.raises(RuntimeError, match="未定義のモデルです: unknown"):
        resolve_ai_model(config, "unknown")


def test_resolve_ai_model_rejects_disallowed_service_type() -> None:
    config = load_config()

    with pytest.raises(RuntimeError, match="services.openai.type"):
        resolve_ai_model(
            config,
            "openai_chat",
            allowed_service_types=("ollama",),
        )


def test_require_embedding_dimension_returns_dimension() -> None:
    config = load_config()
    resolved = resolve_ai_model(config, "openai_embedding")

    assert require_embedding_dimension(resolved) == 1536


def test_require_embedding_dimension_rejects_missing_dimension() -> None:
    config = load_config()
    models = dict(config.models)
    models["openai_embedding"] = ModelSettings(
        service="openai",
        name="text-embedding-3-small",
        dimension=None,
    )
    config = replace(config, models=models)
    resolved = resolve_ai_model(config, "openai_embedding")

    with pytest.raises(RuntimeError, match="models.openai_embedding.dimension"):
        require_embedding_dimension(resolved)
