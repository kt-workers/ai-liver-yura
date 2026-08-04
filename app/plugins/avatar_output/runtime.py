from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

from app.adapters.avatar import HttpAvatarOutput, HttpAvatarOutputConfig
from app.plugins.avatar_output.plugin import AvatarOutputPlugin
from app.shared.contracts.plugins.runtime import PluginContext, SystemClock

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def create_avatar_output_plugin_from_env() -> AvatarOutputPlugin | None:
    """Web MVP向けAvatar Output Pluginを環境変数から構築する。

    最小縦断検証のFactoryであり、CoreのBootstrapパッケージへ依存しない。
    正式なSubsystem統合時はRuntime Plugin Setupへ移し、接続監視と再初期化を
    PluginManagerへ統合する。
    """

    if not _env_enabled("YURA_AVATAR_OUTPUT_ENABLED", default=False):
        return None
    base_url = os.getenv("YURA_AVATAR_RUNTIME_URL", "").strip()
    if not base_url:
        logger.warning(
            "avatar output is enabled but YURA_AVATAR_RUNTIME_URL is empty"
        )
        return None
    timeout_seconds = _env_float(
        "YURA_AVATAR_OUTPUT_TIMEOUT_SECONDS",
        default=3.0,
    )
    adapter = HttpAvatarOutput(
        HttpAvatarOutputConfig(
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        )
    )
    plugin = AvatarOutputPlugin(adapter)
    plugin.initialize(
        PluginContext(
            llm_gateway=_UnavailableLlmGateway(),
            activity_gateway=_UnavailableActivityGateway(),
            clock=SystemClock(),
            configuration={"transport": "http_web_mvp"},
            capability_reporter=_LoggingCapabilityReporter(),
        )
    )
    return plugin


def reset_avatar_output_plugin_cache() -> None:
    """テストまたはRuntime再構成時に環境変数Factoryのキャッシュを破棄する。"""

    create_avatar_output_plugin_from_env.cache_clear()


def _env_enabled(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "off", "no", ""}


def _env_float(name: str, *, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as error:
        raise RuntimeError(f"{name} must be a number") from error
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than zero")
    return value


class _UnavailableLlmGateway:
    async def generate_response(self, activity: Any) -> str:
        raise RuntimeError("avatar_output does not use llm_gateway")


class _UnavailableActivityGateway:
    def register(self, activity: Any) -> Any:
        raise RuntimeError("avatar_output does not register activities")


class _LoggingCapabilityReporter:
    def set_capability_availability(
        self,
        plugin_id: str,
        capability: str,
        *,
        available: bool,
    ) -> None:
        logger.info(
            "avatar capability changed: plugin_id=%s capability=%s available=%s",
            plugin_id,
            capability,
            available,
        )
