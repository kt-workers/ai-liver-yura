"""設定のpublicationを生成し、既存Speech OwnerとS2の接続へ渡す。"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

from app.adapters.llm.character_language import character_language_openai_role_config
from app.adapters.llm.openai_responses import (
    OpenAIResponsesModelPolicy,
    OpenAIResponsesRoleConfig,
    OpenAIResponsesTemperatureMapping,
    model_policy_failure,
)
from app.adapters.llm.speech_semantics import (
    SpeechSemanticsProviderPort,
    speech_semantics_openai_role_config,
    speech_semantics_provider_descriptor,
)
from app.adapters.tts.contracts import TTSVoiceBinding
from app.composition.memory_persistence import CoreMemoryPersistenceBinding
from app.composition.speech_preparation import finish_cleanup
from app.composition.speech_production_configuration import (
    SpeechBindingReference,
    SpeechProductionInputs,
    SpeechProductionPorts,
    SpeechProductionPublication,
)
from app.composition.system_cognition_configuration import S2RunIdentity
from app.config.layered import (
    ConfigurationError,
    ConfigurationFailureCode,
    SpeechDeploymentProfile,
    UserConfiguration,
    load_user_configuration,
)
from app.config.s2_contracts import identity
from app.domain.character_language.realizer import CharacterLanguagePolicy
from app.domain.llm import LLMFailurePolicy, LLMRoleDescriptor
from app.domain.semantic_verification import (
    blind_instructions,
    blind_output_schema,
    relation_instructions,
    relation_output_schema,
)
from app.domain.semantic_verification.verifier import (
    BLIND_INPUT_SCHEMA,
    BLIND_OUTPUT_SCHEMA,
    BLIND_ROLE_ID,
    RELATION_INPUT_SCHEMA,
    RELATION_OUTPUT_SCHEMA,
    RELATION_ROLE_ID,
    SemanticVerificationPolicy,
)
from app.domain.speech_performance.policy import yura_revision_1_policy
from app.domain.speech_semantics.planner import SpeechSemanticsPolicy
from app.domain.speech_semantics.production import SpeechSemanticPolicyOwner


@dataclass(frozen=True, slots=True)
class SpeechDeploymentRequest:
    """信頼された接続先へ渡す実設定。Snapshotや診断へ直列化しない。"""

    publication: SpeechProductionPublication
    deployment: SpeechDeploymentProfile = field(repr=False)
    role_configs: tuple[OpenAIResponsesRoleConfig, ...] = field(repr=False)
    provider_roles: tuple[LLMRoleDescriptor, ...]
    voice: TTSVoiceBinding | None = field(repr=False)


class SpeechDeploymentPortFactory(Protocol):
    async def __call__(self, request: SpeechDeploymentRequest) -> SpeechProductionPorts:
        """既存Owner portsを束ね、返却前の失敗資源は取得側で回収する。"""
        ...


class SpeechDeploymentRegistry:
    """設定による任意importを許さず、起動側が登録した接続だけを選択する。"""

    def __init__(self, factories: Mapping[str, SpeechDeploymentPortFactory]) -> None:
        for key, factory in factories.items():
            identity(key)
            if not callable(factory):
                raise ConfigurationError(ConfigurationFailureCode.BINDING_MISMATCH)
        self._factories = MappingProxyType(dict(factories))

    def resolve(self, name: str) -> SpeechDeploymentPortFactory:
        try:
            return self._factories[name]
        except KeyError:
            raise ConfigurationError(ConfigurationFailureCode.BINDING_MISMATCH) from None


def _role_configs(
    config: UserConfiguration,
) -> tuple[OpenAIResponsesRoleConfig, ...]:
    profile, deployment = config.speech, config.deployment
    assert profile is not None and deployment is not None
    if deployment.llm_availability == "unavailable":
        return ()
    mappings = {row.role_id: row for row in deployment.roles}
    result: list[OpenAIResponsesRoleConfig] = []
    for role_id, execution in zip(
        ("speech_semantics", "character_language", BLIND_ROLE_ID, RELATION_ROLE_ID),
        profile.executions,
        strict=True,
    ):
        row = mappings[role_id]
        policy = OpenAIResponsesModelPolicy(
            deployment.identity + "." + role_id,
            deployment.revision,
            row.model,
            {execution.reasoning_effort: row.reasoning},
            temperature_mapping=(
                None
                if row.temperature_range is None
                else OpenAIResponsesTemperatureMapping(*row.temperature_range)
            ),
            provider_max_output_tokens=row.max_output_tokens,
        )
        if model_policy_failure(execution, policy) is not None:
            raise ConfigurationError(ConfigurationFailureCode.BINDING_MISMATCH)
        models = {execution.model_class: policy}
        if role_id == "speech_semantics":
            role = speech_semantics_openai_role_config(models)
        elif role_id == "character_language":
            # helperのOwner登録を保持し、具体mappingの由来だけをdeploymentへ揃える。
            role = replace(
                character_language_openai_role_config(
                    {execution.model_class: row.model},
                    reasoning_by_effort=policy.reasoning_by_effort,
                ),
                model_policies=models,
            )
        else:
            blind = role_id == BLIND_ROLE_ID
            role = OpenAIResponsesRoleConfig(
                role_id,
                models,
                BLIND_INPUT_SCHEMA if blind else RELATION_INPUT_SCHEMA,
                BLIND_OUTPUT_SCHEMA if blind else RELATION_OUTPUT_SCHEMA,
                "semantic_verification_blind_v1" if blind else "semantic_verification_relation_v1",
                blind_output_schema() if blind else relation_output_schema(),
                blind_instructions() if blind else relation_instructions(),
                LLMFailurePolicy.FAIL_CLOSED,
            )
        result.append(role)
    return tuple(result)


class SpeechDeploymentSource:
    """一つのSystem runに固定し、ファイル変更時は再起動を要求する供給元。"""

    def __init__(
        self,
        root: Path,
        config: UserConfiguration,
        run: S2RunIdentity,
        semantic_owner: SpeechSemanticPolicyOwner,
        memory: CoreMemoryPersistenceBinding,
        registry: SpeechDeploymentRegistry,
    ) -> None:
        p, d = config.speech, config.deployment
        assert p is not None and d is not None
        semantic_publication = semantic_owner.publication()
        subject = semantic_publication.value.projection.runtime_subject_identity
        if subject is None or semantic_publication.value.meaning is None:
            raise ConfigurationError(ConfigurationFailureCode.BINDING_MISMATCH)
        self._root, self._config = root, config
        self._owner, self._semantic_publication = semantic_owner, semantic_publication
        self._factory = registry.resolve(d.connection)
        self._acquired = False
        binding_id = "configuration.speech." + run.runtime_epoch + "." + run.system_run_id
        identity(binding_id)
        publication = SpeechProductionPublication(
            "configuration.files",
            p.identity,
            config.revision,
            binding_id,
            config.revision,
            1,
            subject.character_id,
            subject.character_definition_revision,
            SpeechSemanticsPolicy(
                p.executions[0], meaning_policy=semantic_publication.value.meaning
            ),
            CharacterLanguagePolicy(p.executions[1]),
            SemanticVerificationPolicy(p.executions[2], p.executions[3]),
            yura_revision_1_policy(),
            p.runtime,
            SpeechBindingReference(d.identity + ".llm", d.revision, d.llm_availability),
            SpeechBindingReference(d.identity + ".tts", d.revision, d.tts_availability),
            SpeechBindingReference(
                d.identity + ".presentation", d.revision, d.presentation_availability
            ),
            p.output_modes,
            p.tts_mode,
            p.priority,
            p.runtime.policy_id + ".expiry",
        )
        voice = None
        if d.tts_availability == "available":
            assert (
                d.tts_provider is not None and d.tts_voice is not None and d.tts_locale is not None
            )
            voice = TTSVoiceBinding(
                d.identity + ".tts",
                subject.character_id,
                d.tts_provider,
                d.tts_voice,
                d.revision,
                d.tts_locale,
                True,
            )
        roles = publication.roles()
        self.request = SpeechDeploymentRequest(
            publication,
            d,
            _role_configs(config),
            (speech_semantics_provider_descriptor(publication.semantics), *roles[1:]),
            voice,
        )
        self.inputs = SpeechProductionInputs(
            publication,
            self.current_publication,
            semantic_owner,
            memory,
            self._acquire,
        )

    def current_publication(self) -> SpeechProductionPublication:
        if (
            load_user_configuration(self._root) != self._config
            or self._owner.publication() != self._semantic_publication
        ):
            raise ConfigurationError(ConfigurationFailureCode.STALE)
        return self.request.publication

    async def _acquire(
        self,
        publication: SpeechProductionPublication,
        roles: tuple[LLMRoleDescriptor, ...],
    ) -> SpeechProductionPorts:
        try:
            return await self._acquire_registered(publication, roles)
        except ConfigurationError:
            raise
        except Exception:
            raise ConfigurationError(ConfigurationFailureCode.BINDING_MISMATCH) from None

    async def _acquire_registered(
        self,
        publication: SpeechProductionPublication,
        roles: tuple[LLMRoleDescriptor, ...],
    ) -> SpeechProductionPorts:
        if (
            self._acquired
            or publication != self.current_publication()
            or roles != publication.roles()
        ):
            raise ConfigurationError(ConfigurationFailureCode.BINDING_MISMATCH)
        self._acquired = True
        ports = await self._factory(self.request)
        if not isinstance(ports, SpeechProductionPorts):
            raise ConfigurationError(ConfigurationFailureCode.BINDING_MISMATCH)
        try:
            if (
                ports.publication != publication
                or ports.roles != roles
                or self.current_publication() != publication
            ):
                raise ConfigurationError(ConfigurationFailureCode.BINDING_MISMATCH)
            return replace(ports, llm=SpeechSemanticsProviderPort(ports.llm, publication.semantics))
        except BaseException:

            async def cleanup() -> None:
                await ports.release()

            await finish_cleanup(asyncio.create_task(cleanup()))
            raise


def create_speech_deployment(
    root: Path,
    *,
    run: S2RunIdentity,
    semantic_owner: SpeechSemanticPolicyOwner,
    memory: CoreMemoryPersistenceBinding,
    registry: SpeechDeploymentRegistry,
) -> SpeechDeploymentSource | None:
    """主設定が無効ならNone。有効時は既存S2へ渡す正式入力を作る。"""
    try:
        config = load_user_configuration(root)
        if config.speech is None:
            return None
        if not isinstance(run, S2RunIdentity) or not isinstance(
            memory, CoreMemoryPersistenceBinding
        ):
            raise ConfigurationError(ConfigurationFailureCode.BINDING_MISMATCH)
        return SpeechDeploymentSource(root, config, run, semantic_owner, memory, registry)
    except ConfigurationError:
        raise
    except Exception:
        raise ConfigurationError(ConfigurationFailureCode.BINDING_MISMATCH) from None
