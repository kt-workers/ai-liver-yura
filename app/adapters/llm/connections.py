"""共通LLM接続の設定を既存OpenAI Responses Adapterへ閉じ込める。"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import cast

from app.adapters.llm.appraisal import appraisal_openai_role_config
from app.adapters.llm.production import UnavailableLLMRolePort
from app.adapters.llm.openai_responses import (
    OpenAIResponsesAdapter,
    OpenAIResponsesModelPolicy,
    OpenAIResponsesRoleConfig,
    ResponsesClient,
)
from app.config.llm_connections import LLMConnectionConfig
from app.domain.llm import LLMModelClass, LLMReasoningEffort, LLMRoleDescriptor
from app.infrastructure.llm.connection_registry_factory import LLMConnectionAdapter
from app.usecases.ports.llm import LLMRolePort


@dataclass(frozen=True, slots=True)
class OpenAIResponsesConnectionAdapter(LLMConnectionAdapter):
    """接続設定だけからOpenAI clientを所有し、Roleの意味を設定へ漏らさない。"""

    adapter_id: str = "openai_responses"

    async def connect(
        self,
        connection: object,
        descriptors: tuple[LLMRoleDescriptor, ...],
    ) -> tuple[LLMRolePort, Callable[[], Awaitable[None]]]:
        if not isinstance(connection, LLMConnectionConfig):
            raise ValueError("OpenAI接続の設定型が不正です")
        policies = _policies(connection.settings)
        configs = tuple(_role_config(descriptor, policies) for descriptor in descriptors)
        api_key = os.environ.get("YURA_OPENAI_API_KEY")
        if not api_key:
            # 外部Provider未接続でも必須Brainの構成は維持し、呼出時に型付き失敗を返す。
            async def close_unavailable() -> None:
                return None

            return UnavailableLLMRolePort(descriptors), close_unavailable
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=api_key)
        try:
            port = OpenAIResponsesAdapter(cast(ResponsesClient, client.responses), configs)
        except BaseException:
            await client.close()
            raise
        return port, client.close


def production_llm_connection_adapters() -> tuple[LLMConnectionAdapter, ...]:
    """本番で許可するAdapterを構成層だけが固定する。"""
    return (OpenAIResponsesConnectionAdapter(),)


def _policies(settings: object) -> Mapping[LLMModelClass, OpenAIResponsesModelPolicy]:
    if not isinstance(settings, Mapping) or set(settings) != {"model_mappings"}:
        raise ValueError("OpenAI接続設定が不正です")
    rows = settings["model_mappings"]
    if not isinstance(rows, tuple):
        raise ValueError("OpenAI接続のmodel_mappingsが不正です")
    policies: dict[LLMModelClass, OpenAIResponsesModelPolicy] = {}
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != {
            "model_class", "mapping_id", "mapping_revision", "model", "reasoning_by_effort"
        }:
            raise ValueError("OpenAI接続のmodel mappingが不正です")
        reasoning_raw = row["reasoning_by_effort"]
        if not isinstance(reasoning_raw, Mapping):
            raise ValueError("OpenAI接続のreasoning mappingが不正です")
        model_class = LLMModelClass(cast(str, row["model_class"]))
        if model_class in policies:
            raise ValueError("OpenAI接続のmodel classが重複しています")
        policies[model_class] = OpenAIResponsesModelPolicy(
            cast(str, row["mapping_id"]),
            cast(int, row["mapping_revision"]),
            cast(str, row["model"]),
            {
                LLMReasoningEffort(cast(str, effort)): cast(str, value)
                for effort, value in reasoning_raw.items()
            },
        )
    if not policies:
        raise ValueError("OpenAI接続のmodel mappingがありません")
    return policies


def _role_config(
    descriptor: LLMRoleDescriptor,
    policies: Mapping[LLMModelClass, OpenAIResponsesModelPolicy],
) -> OpenAIResponsesRoleConfig:
    if descriptor.role_id == "subjective_appraisal":
        return appraisal_openai_role_config(policies)
    return OpenAIResponsesRoleConfig(
        descriptor.role_id,
        policies,
        descriptor.input_schema_id,
        descriptor.output_schema_id,
        f"{descriptor.role_id}_v1".replace(".", "_"),
        _output_schema(descriptor.role_id),
        descriptor.responsibility,
        descriptor.failure_policy,
    )


def _output_schema(role_id: str) -> Mapping[str, object]:
    fields = {
        "input_meaning": (
            "speech_act primary_intent expected_response target_ref entities references "
            "information negated hypothetical temporal_relation confidence unresolved_fields"
        ),
        "executive_deliberation": (
            "candidate_id trigger_id source_event_ids source_context_revision goal_revision "
            "attention_revision outcome priority interruptibility intents goal_transition_intents "
            "commitment_transition_intents rationale_refs"
        ),
    }.get(role_id)
    if fields is None:
        raise ValueError("Roleの構造出力契約が未登録です")
    return {
        "type": "object",
        "additionalProperties": False,
        "required": fields.split(),
        "properties": {field: {} for field in fields.split()},
    }
