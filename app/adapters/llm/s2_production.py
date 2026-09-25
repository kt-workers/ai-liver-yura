"""S2構成から認証を隔離し、生成したSDK clientだけをleaseで所有する。"""

import asyncio
import os
from typing import cast

from app.adapters.llm.openai_responses import (
    OpenAIResponsesAdapter,
    OpenAIResponsesRoleConfig,
    ResponsesClient,
)
from app.adapters.llm.production import UnavailableLLMRolePort
from app.composition.s2_provider import ProviderBindingSnapshot, S2ProviderLease
from app.config.s2_contracts import S2ConfigurationError, S2FailureCode
from app.domain.llm import LLMRoleDescriptor


async def create_s2_provider_lease(
    roles: tuple[LLMRoleDescriptor, ...],
    configs: tuple[OpenAIResponsesRoleConfig, ...],
    bindings: tuple[ProviderBindingSnapshot, ...],
    mode: str,
) -> S2ProviderLease:
    """秘密はこの境界内に留め、未構成と構成不正を区別する。"""
    configured = bool(os.environ.get("OPENAI_API_KEY"))
    if mode not in ("configured", "unconfigured") or configured != (mode == "configured"):
        raise S2ConfigurationError(S2FailureCode.PROVIDER_MAPPING_FAILED)
    if not configured:
        if configs:
            raise S2ConfigurationError(S2FailureCode.PROVIDER_MAPPING_FAILED)

        async def release() -> None:
            return None

        return S2ProviderLease(UnavailableLLMRolePort(roles), bindings, mode, release)
    from openai import AsyncOpenAI

    client = AsyncOpenAI()
    try:
        port = OpenAIResponsesAdapter(cast(ResponsesClient, client.responses), configs)
        return S2ProviderLease(port, bindings, mode, client.close)
    except BaseException:
        from app.bootstrap import _reap_cleanup

        await _reap_cleanup(asyncio.create_task(client.close()))
        raise
