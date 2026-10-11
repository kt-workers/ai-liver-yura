"""Owner設定を複製せず、cognition_coreの明示参照を厳密に読み込む。"""

from dataclasses import dataclass

from app.config.cognition_core_contracts import identity, invalid, parse, resource, revision, shape


@dataclass(frozen=True, slots=True)
class ConfigurationReference:
    resource_ref: str
    config_id: str
    config_revision: int

    def __post_init__(self) -> None:
        resource(self.resource_ref)
        identity(self.config_id)
        revision(self.config_revision)


@dataclass(frozen=True, slots=True)
class AttentionPolicyReference:
    policy_id: str
    policy_revision: int

    def __post_init__(self) -> None:
        identity(self.policy_id)
        revision(self.policy_revision)


@dataclass(frozen=True, slots=True)
class ProviderDeploymentReference:
    resource_ref: str
    deployment_id: str
    deployment_revision: int

    def __post_init__(self) -> None:
        resource(self.resource_ref)
        identity(self.deployment_id)
        revision(self.deployment_revision)


@dataclass(frozen=True, slots=True)
class CharacterDefinitionReference:
    resource_ref: str
    character_id: str
    definition_revision: int

    def __post_init__(self) -> None:
        resource(self.resource_ref)
        identity(self.character_id)
        revision(self.definition_revision)


@dataclass(frozen=True, slots=True)
class CognitionCoreConfig:
    schema_id: str
    config_id: str
    config_revision: int
    activation_id: str
    composition_id: str
    composition_revision: int
    minimum_config: ConfigurationReference
    appraisal_config: ConfigurationReference
    executive_config: ConfigurationReference
    attention_policy: AttentionPolicyReference
    provider_deployment: ProviderDeploymentReference
    character_definition: CharacterDefinitionReference

    def __post_init__(self) -> None:
        if (
            self.schema_id != "yura.cognition.core-config.v1"
            or self.config_id != "yura.cognition.core"
            or self.activation_id != "yura.cognition.core.explicit"
            or self.composition_id != "yura.system.cognition.core"
        ):
            invalid()
        revision(self.config_revision)
        revision(self.composition_revision)
        if (
            not all(
                isinstance(ref, ConfigurationReference)
                for ref in (self.minimum_config, self.appraisal_config, self.executive_config)
            )
            or not isinstance(self.attention_policy, AttentionPolicyReference)
            or not isinstance(self.provider_deployment, ProviderDeploymentReference)
            or not isinstance(self.character_definition, CharacterDefinitionReference)
        ):
            invalid()


def _config_ref(value: object) -> ConfigurationReference:
    data = shape(value, "resource_ref config_id config_revision")
    return ConfigurationReference(
        resource(data["resource_ref"]),
        identity(data["config_id"]),
        revision(data["config_revision"]),
    )


def load_cognition_core_config(source: str | bytes) -> CognitionCoreConfig:
    data = shape(
        parse(source),
        "schema_id config_id config_revision activation_id composition_id "
        "composition_revision minimum_config appraisal_config executive_config "
        "attention_policy provider_deployment character_definition",
    )
    attention = shape(data["attention_policy"], "policy_id policy_revision")
    provider = shape(data["provider_deployment"], "resource_ref deployment_id deployment_revision")
    character = shape(data["character_definition"], "resource_ref character_id definition_revision")
    return CognitionCoreConfig(
        identity(data["schema_id"]),
        identity(data["config_id"]),
        revision(data["config_revision"]),
        identity(data["activation_id"]),
        identity(data["composition_id"]),
        revision(data["composition_revision"]),
        _config_ref(data["minimum_config"]),
        _config_ref(data["appraisal_config"]),
        _config_ref(data["executive_config"]),
        AttentionPolicyReference(
            identity(attention["policy_id"]), revision(attention["policy_revision"])
        ),
        ProviderDeploymentReference(
            resource(provider["resource_ref"]),
            identity(provider["deployment_id"]),
            revision(provider["deployment_revision"]),
        ),
        CharacterDefinitionReference(
            resource(character["resource_ref"]),
            identity(character["character_id"]),
            revision(character["definition_revision"]),
        ),
    )
