"""core構成から認証を隔離し、生成したSDK clientだけをleaseで所有する。"""

import asyncio
import os
from typing import cast

from app.adapters.llm.openai_responses import (
    OpenAIResponsesAdapter,
    OpenAIResponsesRoleConfig,
    ResponsesClient,
)
from app.adapters.llm.production import UnavailableLLMRolePort
from app.composition.core_provider import ProviderBindingSnapshot, CoreProviderLease
from app.config.core_contracts import CoreConfigurationError, CoreFailureCode
from app.domain.llm import LLMRoleDescriptor


async def create_core_provider_lease(
    roles: tuple[LLMRoleDescriptor, ...],
    configs: tuple[OpenAIResponsesRoleConfig, ...],
    bindings: tuple[ProviderBindingSnapshot, ...],
    mode: str,
) -> CoreProviderLease:
    """秘密はこの境界内に留め、未構成と構成不正を区別する。"""
    api_key = os.environ.get("YURA_OPENAI_API_KEY")
    if mode not in ("configured", "unconfigured"):
        raise CoreConfigurationError(CoreFailureCode.PROVIDER_MAPPING_FAILED)
    if mode == "unconfigured":
        if configs:
            raise CoreConfigurationError(CoreFailureCode.PROVIDER_MAPPING_FAILED)

        async def release() -> None:
            return None

        return CoreProviderLease(UnavailableLLMRolePort(roles), bindings, mode, release)
    if not api_key:
        raise CoreConfigurationError(CoreFailureCode.PROVIDER_MAPPING_FAILED)
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key)
    try:
        port = OpenAIResponsesAdapter(cast(ResponsesClient, client.responses), configs)
        return CoreProviderLease(port, bindings, mode, client.close)
    except BaseException:
        from app.application import _reap_cleanup

        await _reap_cleanup(asyncio.create_task(client.close()))
        raise
