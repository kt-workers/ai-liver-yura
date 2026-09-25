"""Speech意味Ownerの登録と可逆搬送を汎用Providerの外側で接続する。"""

from collections.abc import Mapping
from dataclasses import replace

from app.domain.llm import (
    LLMFailureCode,
    LLMFailurePolicy,
    LLMModelClass,
    LLMRoleDescriptor,
    LLMRoleFailure,
    LLMRoleRequest,
    LLMRoleResult,
    LLMRoleStatus,
    StructuredPayload,
    validate_role_exchange,
)
from app.domain.speech_semantics.planner import (
    INPUT_SCHEMA,
    OUTPUT_SCHEMA,
    ROLE_ID,
    SpeechSemanticsPolicy,
    descriptor,
)
from app.domain.speech_semantics.schemas import (
    PROVIDER_OUTPUT_SCHEMA,
    decode_speech_semantics_output,
    speech_semantics_instructions,
    speech_semantics_output_schema,
)
from app.usecases.ports.llm import LLMRolePort

from .openai_responses import OpenAIResponsesModelPolicy, OpenAIResponsesRoleConfig

SPEECH_SEMANTICS_PROVIDER_FORMAT_NAME = "speech_semantics_candidate_wire_v1"


def speech_semantics_openai_role_config(
    model_policies: Mapping[LLMModelClass, OpenAIResponsesModelPolicy],
) -> OpenAIResponsesRoleConfig:
    """deploymentの具体mappingを保持し、意味Ownerの登録だけを提供する。"""
    if not isinstance(model_policies, Mapping):
        raise ValueError("Speech SemanticsのProvider方針にはMappingが必要です")
    policies = dict(model_policies)
    allowed = {LLMModelClass.FAST, LLMModelClass.BALANCED, LLMModelClass.DEEP_REASONING}
    if not policies or any(not isinstance(k, LLMModelClass) or k not in allowed for k in policies):
        raise ValueError("Speech Semanticsのmodel class登録が不正です")
    return OpenAIResponsesRoleConfig(
        role_id=ROLE_ID,
        model_policies=policies,
        input_schema_id=INPUT_SCHEMA,
        output_schema_id=PROVIDER_OUTPUT_SCHEMA,
        provider_output_format_name=SPEECH_SEMANTICS_PROVIDER_FORMAT_NAME,
        output_json_schema=speech_semantics_output_schema(),
        instructions=speech_semantics_instructions(),
        failure_policy=LLMFailurePolicy.FAIL_CLOSED,
    )


def speech_semantics_provider_descriptor(policy: SpeechSemanticsPolicy) -> LLMRoleDescriptor:
    """汎用Providerへの登録ではwire schemaを正確に表示する。"""
    return replace(descriptor(policy), output_schema_id=PROVIDER_OUTPUT_SCHEMA)


class SpeechSemanticsProviderPort:
    """借用Providerを所有せず、対象Roleの成功payloadだけをDomainへ復元する。"""

    def __init__(self, port: LLMRolePort, policy: SpeechSemanticsPolicy) -> None:
        self._port = port
        self._policy = policy

    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
        result = await self._port.invoke(request)
        if request.role_id != ROLE_ID or result.status is not LLMRoleStatus.SUCCEEDED:
            return result
        failure = validate_role_exchange(
            speech_semantics_provider_descriptor(self._policy),
            request,
            result,
        )
        if failure is None and result.output is not None:
            try:
                value = decode_speech_semantics_output(
                    result.output.value,
                    created_at=result.completed_at,
                    bounds_policy=self._policy.bounds_policy,
                )
                return replace(result, output=StructuredPayload(OUTPUT_SCHEMA, value))
            except ValueError:
                pass
        return replace(
            result,
            status=LLMRoleStatus.FAILED,
            output=None,
            failure=LLMRoleFailure(
                LLMFailureCode.SCHEMA_INVALID,
                "Speech SemanticsのProvider出力が登録契約に一致しません",
            ),
        )
