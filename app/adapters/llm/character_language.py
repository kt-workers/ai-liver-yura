from __future__ import annotations

from collections.abc import Mapping

from app.domain.character_language.realizer import INPUT_SCHEMA, OUTPUT_SCHEMA, ROLE_ID
from app.domain.character_language.schemas import (
    character_language_instructions,
    character_language_output_schema,
)
from app.domain.llm import LLMFailurePolicy, LLMModelClass, LLMReasoningEffort

from .openai_responses import OpenAIResponsesModelPolicy, OpenAIResponsesRoleConfig

CHARACTER_LANGUAGE_PROVIDER_FORMAT_NAME = "character_language_candidate_v1"
_ALLOWED_MODEL_CLASSES = frozenset(
    {
        LLMModelClass.FAST,
        LLMModelClass.BALANCED,
        LLMModelClass.DEEP_REASONING,
    }
)


def _reasoning_mapping(
    reasoning_by_effort: Mapping[LLMReasoningEffort, str],
) -> dict[LLMReasoningEffort, str]:
    if not isinstance(reasoning_by_effort, Mapping):
        raise ValueError("Character Language reasoning mappingはMappingでなければなりません")
    mapping = dict(reasoning_by_effort)
    if not mapping or any(
        not isinstance(effort, LLMReasoningEffort)
        or not isinstance(value, str)
        or not value.strip()
        for effort, value in mapping.items()
    ):
        raise ValueError("Character Language reasoning mappingが不正です")
    return mapping


def character_language_openai_role_config(
    model_by_class: Mapping[LLMModelClass, str],
    *,
    reasoning_by_effort: Mapping[LLMReasoningEffort, str],
) -> OpenAIResponsesRoleConfig:
    """#330 production Roleを#357 OpenAI Responses Adapterへ登録する。"""

    if not isinstance(model_by_class, Mapping):
        raise ValueError("Character Language model mappingはMappingでなければなりません")
    models = dict(model_by_class)
    if not models:
        raise ValueError("Character Language model mappingは空にできません")
    if any(
        not isinstance(model_class, LLMModelClass)
        or model_class not in _ALLOWED_MODEL_CLASSES
        or not isinstance(model, str)
        or not model.strip()
        for model_class, model in models.items()
    ):
        raise ValueError("Character Language model mappingが不正です")

    reasoning = _reasoning_mapping(reasoning_by_effort)
    policies = {
        model_class: OpenAIResponsesModelPolicy(model, reasoning)
        for model_class, model in models.items()
    }
    return OpenAIResponsesRoleConfig(
        role_id=ROLE_ID,
        model_policies=policies,
        input_schema_id=INPUT_SCHEMA,
        output_schema_id=OUTPUT_SCHEMA,
        provider_output_format_name=CHARACTER_LANGUAGE_PROVIDER_FORMAT_NAME,
        output_json_schema=character_language_output_schema(),
        instructions=character_language_instructions(),
        failure_policy=LLMFailurePolicy.FAIL_CLOSED,
    )


def character_language_openai_role_configs(
    model_by_class: Mapping[LLMModelClass, str],
    *,
    reasoning_by_effort: Mapping[LLMReasoningEffort, str],
) -> tuple[OpenAIResponsesRoleConfig, ...]:
    """OpenAIResponsesAdapter.from_environment()へ渡すproduction registration tuple。"""

    return (
        character_language_openai_role_config(
            model_by_class,
            reasoning_by_effort=reasoning_by_effort,
        ),
    )


__all__ = [
    "CHARACTER_LANGUAGE_PROVIDER_FORMAT_NAME",
    "character_language_openai_role_config",
    "character_language_openai_role_configs",
]
