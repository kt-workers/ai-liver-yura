from dataclasses import replace

import pytest

from app.bootstrap.service_settings import (
    resolve_database_service,
    resolve_http_ai_service,
    resolve_service,
)
from app.config.app_config import load_app_config


def test_resolves_core_ai_and_database_services() -> None:
    config = load_app_config()
    assert resolve_http_ai_service(config, "openai").type == "openai"
    assert resolve_database_service(config, "topic_memory_database").type == "postgres"


def test_resolve_service_reports_missing_name() -> None:
    config = replace(load_app_config(), services={})
    with pytest.raises(RuntimeError, match="未定義のサービスです: openai"):
        resolve_service(config, "openai")
