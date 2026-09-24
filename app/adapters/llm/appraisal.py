"""Appraisal固有契約と外部注入されたProvider方針を結び付ける。"""

from collections.abc import Mapping

from app.domain.appraisal.deep import INPUT_SCHEMA, OUTPUT_SCHEMA, ROLE_ID
from app.domain.appraisal.schemas import appraisal_instructions, appraisal_output_schema
from app.domain.llm import LLMFailurePolicy, LLMModelClass

from .openai_responses import OpenAIResponsesModelPolicy, OpenAIResponsesRoleConfig

APPRAISAL_PROVIDER_FORMAT_NAME = "subjective_appraisal_candidate_v1"


def appraisal_openai_role_config(
    model_policies: Mapping[LLMModelClass, OpenAIResponsesModelPolicy],
) -> OpenAIResponsesRoleConfig:
    """mappingの値と世代を保持し、Appraisalの論理契約だけを登録する。"""
    if not isinstance(model_policies, Mapping):
        raise ValueError("AppraisalのProvider方針にはMappingが必要です")
    policies = dict(model_policies)
    allowed = {LLMModelClass.FAST, LLMModelClass.BALANCED, LLMModelClass.DEEP_REASONING}
    if not policies or any(
        not isinstance(key, LLMModelClass) or key not in allowed for key in policies
    ):
        raise ValueError("Appraisalのmodel class登録が不正です")
    return OpenAIResponsesRoleConfig(
        role_id=ROLE_ID,
        model_policies=policies,
        input_schema_id=INPUT_SCHEMA,
        output_schema_id=OUTPUT_SCHEMA,
        provider_output_format_name=APPRAISAL_PROVIDER_FORMAT_NAME,
        output_json_schema=appraisal_output_schema(),
        instructions=appraisal_instructions(),
        failure_policy=LLMFailurePolicy.SKIP_OPTIONAL,
    )
