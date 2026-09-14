"""Reflectionの論理Roleを既存OpenAI Adapterへ登録するfactory。"""

from collections.abc import Mapping

from app.domain.llm import LLMFailurePolicy, LLMModelClass, LLMReasoningEffort
from app.domain.memory_reflection.llm_roles import (
    PROPOSAL_INPUT_SCHEMA,
    PROPOSAL_OUTPUT_SCHEMA,
    PROPOSAL_ROLE_ID,
    SUPPORT_INPUT_SCHEMA,
    SUPPORT_OUTPUT_SCHEMA,
    SUPPORT_ROLE_ID,
)
from app.domain.memory_reflection.schemas import (
    proposal_instructions_v3,
    proposal_output_schema_v3,
    support_instructions_v3,
    support_output_schema,
)

from .openai_responses import OpenAIResponsesModelPolicy, OpenAIResponsesRoleConfig

PROPOSAL_FORMAT_NAME = "memory_reflection_candidates_v3"
SUPPORT_FORMAT_NAME = "memory_reflection_support_observation_v1"


def _config(
    role: str,
    input_schema: str,
    output_schema: str,
    format_name: str,
    schema: dict[str, object],
    instructions: str,
    model_by_class: Mapping[LLMModelClass, str],
    reasoning_by_effort: Mapping[LLMReasoningEffort, str],
) -> OpenAIResponsesRoleConfig:
    if not isinstance(model_by_class, Mapping) or not isinstance(reasoning_by_effort, Mapping):
        raise ValueError("Reflectionのmodel/reasoning mappingを明示してください")
    models, reasoning = dict(model_by_class), dict(reasoning_by_effort)
    allowed = {LLMModelClass.FAST, LLMModelClass.BALANCED, LLMModelClass.DEEP_REASONING}
    if not models or any(
        not isinstance(k, LLMModelClass)
        or k not in allowed
        or not isinstance(v, str)
        or not v.strip()
        for k, v in models.items()
    ):
        raise ValueError("Reflectionのmodel mappingが不正です")
    if not reasoning or any(
        not isinstance(k, LLMReasoningEffort) or not isinstance(v, str) or not v.strip()
        for k, v in reasoning.items()
    ):
        raise ValueError("Reflectionのreasoning mappingが不正です")
    return OpenAIResponsesRoleConfig(
        role,
        {
            k: OpenAIResponsesModelPolicy(f"{role}.openai.{k.value}", 1, v, reasoning)
            for k, v in models.items()
        },
        input_schema,
        output_schema,
        format_name,
        schema,
        instructions,
        LLMFailurePolicy.FAIL_CLOSED,
    )


def reflection_proposal_openai_role_config(
    model_by_class: Mapping[LLMModelClass, str],
    *,
    reasoning_by_effort: Mapping[LLMReasoningEffort, str],
) -> OpenAIResponsesRoleConfig:
    return _config(
        PROPOSAL_ROLE_ID,
        PROPOSAL_INPUT_SCHEMA,
        PROPOSAL_OUTPUT_SCHEMA,
        PROPOSAL_FORMAT_NAME,
        proposal_output_schema_v3(),
        proposal_instructions_v3(),
        model_by_class,
        reasoning_by_effort,
    )


def reflection_support_openai_role_config(
    model_by_class: Mapping[LLMModelClass, str],
    *,
    reasoning_by_effort: Mapping[LLMReasoningEffort, str],
) -> OpenAIResponsesRoleConfig:
    return _config(
        SUPPORT_ROLE_ID,
        SUPPORT_INPUT_SCHEMA,
        SUPPORT_OUTPUT_SCHEMA,
        SUPPORT_FORMAT_NAME,
        support_output_schema(),
        support_instructions_v3(),
        model_by_class,
        reasoning_by_effort,
    )
