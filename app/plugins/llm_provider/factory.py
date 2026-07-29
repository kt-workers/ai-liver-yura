from __future__ import annotations

from typing import cast

from app.plugins.llm_provider.plugin import LlmProviderPlugin
from app.shared.contracts.plugins.factory import PluginFactoryContext
from app.shared.contracts.plugins.runtime import ResponseGenerationGateway


class LlmProviderPluginFactory:
    """共有Generator契約からrole別LLM Provider Pluginを生成するFactory。"""

    def create_plugin(
        self,
        context: PluginFactoryContext,
    ) -> LlmProviderPlugin:
        role = context.configuration.get("role")
        configured_available = context.configuration.get("configured_available")
        generator = context.services.get("response_generator")

        if not isinstance(role, str):
            raise TypeError("llm_provider.role must be str")
        if not role:
            raise ValueError("llm_provider.role must not be empty")
        if not isinstance(configured_available, bool):
            raise TypeError("llm_provider.configured_available must be bool")
        if not callable(getattr(generator, "generate_response", None)):
            raise TypeError(
                "llm_provider.response_generator must implement generate_response()"
            )

        return LlmProviderPlugin(
            role,
            cast(ResponseGenerationGateway, generator),
            configured_available=configured_available,
        )


plugin_factory = LlmProviderPluginFactory()
