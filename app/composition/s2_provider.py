"""deployment供給を固定し、Providerの資源所有と安全な由来を結び付ける。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Protocol

from jsonschema import Draft202012Validator

from app.adapters.llm.appraisal import appraisal_openai_role_config
from app.adapters.llm.openai_responses import (
    OpenAIResponsesModelPolicy,
    OpenAIResponsesRoleConfig,
    model_policy_failure,
)
from app.config.provider_deployment import ProviderDeploymentConfig, ProviderSourceReference
from app.config.s2_contracts import S2ConfigurationError, S2FailureCode, identity
from app.domain.llm import LLMModelClass, LLMRoleDescriptor
from app.usecases.ports.llm import LLMRolePort


@dataclass(frozen=True, slots=True)
class ModelPoliciesPublication:
    reference: ProviderSourceReference
    policies: Mapping[LLMModelClass, OpenAIResponsesModelPolicy]

    def __post_init__(self) -> None:
        policies = dict(self.policies)
        if (
            not isinstance(self.reference, ProviderSourceReference)
            or not policies
            or any(
                not isinstance(k, LLMModelClass) or not isinstance(v, OpenAIResponsesModelPolicy)
                for k, v in policies.items()
            )
        ):
            raise S2ConfigurationError(S2FailureCode.PROVIDER_MAPPING_FAILED)
        for value in policies.values():
            identity(value.mapping_id)
        object.__setattr__(self, "policies", MappingProxyType(policies))


@dataclass(frozen=True, slots=True, init=False)
class RoleConfigPublication:
    """可変JSON schemaを参照共有せず、publication内には不変な形式で保存する。"""

    reference: ProviderSourceReference
    _config: OpenAIResponsesRoleConfig = field(repr=False, compare=False)
    _schema: str = field(repr=False)

    def __init__(self, reference: ProviderSourceReference, config: OpenAIResponsesRoleConfig):
        if not isinstance(reference, ProviderSourceReference) or not isinstance(
            config, OpenAIResponsesRoleConfig
        ):
            raise S2ConfigurationError(S2FailureCode.PROVIDER_MAPPING_FAILED)
        schema = json.dumps(dict(config.output_json_schema), sort_keys=True, allow_nan=False)
        object.__setattr__(self, "reference", reference)
        object.__setattr__(self, "_schema", schema)
        object.__setattr__(
            self, "_config", replace(config, output_json_schema=MappingProxyType({}))
        )

    @property
    def config(self) -> OpenAIResponsesRoleConfig:
        return replace(self._config, output_json_schema=json.loads(self._schema))


class S2ProviderConfigurationSource(Protocol):
    def resolve_model_policies(
        self, role_id: str, mapping_ref: ProviderSourceReference
    ) -> ModelPoliciesPublication: ...

    def resolve_role_config(
        self,
        role_id: str,
        role_config_ref: ProviderSourceReference,
        model_policies: Mapping[LLMModelClass, OpenAIResponsesModelPolicy],
    ) -> RoleConfigPublication: ...


@dataclass(frozen=True, slots=True)
class ProviderBindingSnapshot:
    role_id: str
    availability_mode: str
    deployment_id: str
    deployment_revision: int
    mapping_ref: ProviderSourceReference | None
    role_config_ref: ProviderSourceReference | None
    mappings: tuple[tuple[str, str, int, tuple[str, ...]], ...]
    input_schema_id: str
    output_schema_id: str
    provider_output_format_name: str | None


@dataclass(frozen=True, slots=True)
class S2ProviderLease:
    port: LLMRolePort
    bindings: tuple[ProviderBindingSnapshot, ...]
    availability_mode: str
    release_owned: Callable[[], Awaitable[None]] = field(repr=False, compare=False)
    _release_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)

    async def release(self) -> None:
        from app.bootstrap import _reap_cleanup

        if self._release_task is None:
            object.__setattr__(self, "_release_task", asyncio.create_task(self._release()))
        assert self._release_task is not None
        await _reap_cleanup(self._release_task)

    async def _release(self) -> None:
        await self.release_owned()


class S2ProviderLeaseFactory(Protocol):
    async def __call__(
        self,
        roles: tuple[LLMRoleDescriptor, ...],
        configs: tuple[OpenAIResponsesRoleConfig, ...],
        bindings: tuple[ProviderBindingSnapshot, ...],
        mode: str,
    ) -> S2ProviderLease: ...


def resolve_provider_configuration(
    manifest: ProviderDeploymentConfig,
    roles: tuple[LLMRoleDescriptor, ...],
    source: S2ProviderConfigurationSource | None,
) -> tuple[tuple[OpenAIResponsesRoleConfig, ...], tuple[ProviderBindingSnapshot, ...]]:
    try:
        return _resolve(manifest, roles, source)
    except Exception:
        raise S2ConfigurationError(S2FailureCode.PROVIDER_MAPPING_FAILED) from None


def _resolve(
    manifest: ProviderDeploymentConfig,
    roles: tuple[LLMRoleDescriptor, ...],
    source: S2ProviderConfigurationSource | None,
) -> tuple[tuple[OpenAIResponsesRoleConfig, ...], tuple[ProviderBindingSnapshot, ...]]:
    descriptors = {role.role_id: role for role in roles}
    if len(descriptors) != len(roles) or set(descriptors) != {
        binding.role_id for binding in manifest.role_bindings
    }:
        raise ValueError("S2のRole登録が一致しません")
    configs: list[OpenAIResponsesRoleConfig] = []
    snapshots: list[ProviderBindingSnapshot] = []
    captured: list[tuple[str, ModelPoliciesPublication, RoleConfigPublication]] = []
    for binding in manifest.role_bindings:
        role = descriptors[binding.role_id]
        config = None
        mapping_rows: tuple[tuple[str, str, int, tuple[str, ...]], ...] = ()
        if binding.availability_mode == "configured":
            if source is None or binding.mapping_ref is None or binding.role_config_ref is None:
                raise ValueError("構成済みRoleの供給元がありません")
            models = source.resolve_model_policies(role.role_id, binding.mapping_ref)
            publication = source.resolve_role_config(
                role.role_id, binding.role_config_ref, models.policies
            )
            if (
                models.reference != binding.mapping_ref
                or publication.reference != binding.role_config_ref
            ):
                raise ValueError("供給元のリビジョンが一致しません")
            config = publication.config
            if role.role_id == "subjective_appraisal":
                expected = appraisal_openai_role_config(models.policies)
                if config != expected:
                    raise ValueError("AppraisalのOwner構成が一致しません")
                config = expected
            elif config.instructions != role.responsibility:
                raise ValueError("RoleのinstructionsがOwner契約と一致しません")
            if (
                config.role_id != role.role_id
                or config.input_schema_id != role.input_schema_id
                or config.output_schema_id != role.output_schema_id
                or config.failure_policy != role.failure_policy
                or config.model_policies != models.policies
            ):
                raise ValueError("Role構成がOwner契約と一致しません")
            Draft202012Validator.check_schema(dict(config.output_json_schema))
            policy = role.default_execution_policy
            model = models.policies.get(policy.model_class)
            if model is None or policy.reasoning_effort not in model.reasoning_by_effort:
                raise ValueError("論理実行要求に対応するmappingがありません")
            if model_policy_failure(policy, model) is not None:
                raise ValueError("Provider数値対応が不正です")
            mapping_rows = tuple(
                (
                    key.value,
                    value.mapping_id,
                    value.mapping_revision,
                    tuple(effort.value for effort in value.reasoning_by_effort),
                )
                for key, value in models.policies.items()
            )
            configs.append(config)
            captured.append((role.role_id, models, publication))
        snapshots.append(
            ProviderBindingSnapshot(
                role.role_id,
                binding.availability_mode,
                manifest.deployment_id,
                manifest.deployment_revision,
                binding.mapping_ref,
                binding.role_config_ref,
                mapping_rows,
                role.input_schema_id,
                role.output_schema_id,
                None if config is None else config.provider_output_format_name,
            )
        )
    if len({config.provider_output_format_name for config in configs}) != len(configs):
        raise ValueError("出力format名が重複しています")
    if source is not None:
        for role_id, models, publication in captured:
            current = source.resolve_model_policies(role_id, models.reference)
            current_role = source.resolve_role_config(
                role_id, publication.reference, current.policies
            )
            if (
                current != models
                or current_role.reference != publication.reference
                or current_role.config != publication.config
            ):
                raise ValueError("構築中に供給元が更新されました")
    return tuple(configs), tuple(snapshots)
