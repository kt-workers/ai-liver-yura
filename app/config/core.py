"""Owner設定を複製せず、coreの明示参照を厳密に読み込む。"""

from dataclasses import dataclass
from math import isfinite

from app.config.core_contracts import identity, invalid, parse, resource, revision, shape
from app.domain.brain_integration import BrainIntegrationRuntimePolicy
from app.domain.input_meaning import InputMeaningAcceptancePolicy, InputMeaningPolicy, PrimaryIntent
from app.domain.llm import (
    LLMExecutionPolicy,
    LLMModelClass,
    LLMReasoningEffort,
    LLMRequestRetryPolicy,
)
from app.runtime.kernel import LaneErrorPolicy, QueuePolicy, RuntimeLanePolicy, RuntimeSchedulerPolicy
from app.runtime.shutdown import RuntimeShutdownPolicy


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
class CoreConfig:
    schema_id: str
    config_id: str
    config_revision: int
    activation_id: str
    composition_id: str
    composition_revision: int
    appraisal_config: ConfigurationReference
    executive_config: ConfigurationReference
    attention_policy: AttentionPolicyReference
    provider_deployment: ProviderDeploymentReference
    character_definition: CharacterDefinitionReference
    input_meaning_policy: InputMeaningPolicy
    scheduler_policy: RuntimeSchedulerPolicy
    integration_policy: BrainIntegrationRuntimePolicy
    shutdown_policy: RuntimeShutdownPolicy

    def __post_init__(self) -> None:
        if (
            self.schema_id != "yura.core-config.v1"
            or self.config_id != "yura.core"
            or self.activation_id != "yura.core.explicit"
            or self.composition_id != "yura.system.core"
        ):
            invalid()
        revision(self.config_revision)
        revision(self.composition_revision)
        if (
            not all(
                isinstance(ref, ConfigurationReference)
                for ref in (self.appraisal_config, self.executive_config)
            )
            or not isinstance(self.attention_policy, AttentionPolicyReference)
            or not isinstance(self.provider_deployment, ProviderDeploymentReference)
            or not isinstance(self.character_definition, CharacterDefinitionReference)
        ):
            invalid()


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        invalid()
    return value


def _integer(value: object) -> int:
    if type(value) is not int:
        invalid()
    return value


def _number(value: object) -> float:
    if type(value) not in (int, float) or not isfinite(value):
        invalid()
    return float(value)


def _sequence(value: object) -> list[object]:
    if not isinstance(value, list):
        invalid()
    return list(value)


def _execution(value: object) -> LLMExecutionPolicy:
    data = shape(
        value,
        "policy_id policy_revision model_class reasoning_effort timeout_seconds "
        "max_attempts max_output_tokens temperature_normalized retry_policy",
    )
    retry = shape(
        data["retry_policy"], "initial_backoff_seconds backoff_multiplier max_backoff_seconds"
    )
    temperature = data["temperature_normalized"]
    return LLMExecutionPolicy(
        policy_id=_text(data["policy_id"]),
        policy_revision=_integer(data["policy_revision"]),
        model_class=LLMModelClass(_text(data["model_class"])),
        reasoning_effort=LLMReasoningEffort(_text(data["reasoning_effort"])),
        timeout_seconds=_number(data["timeout_seconds"]),
        max_attempts=_integer(data["max_attempts"]),
        max_output_tokens=_integer(data["max_output_tokens"]),
        temperature_normalized=None if temperature is None else _number(temperature),
        retry_policy=LLMRequestRetryPolicy(
            _number(retry["initial_backoff_seconds"]),
            _number(retry["backoff_multiplier"]),
            _number(retry["max_backoff_seconds"]),
        ),
    )


def _meaning(value: object) -> InputMeaningPolicy:
    data = shape(value, "acceptance execution")
    acceptance = shape(
        data["acceptance"],
        "policy_id policy_revision clarification_confidence_threshold "
        "required_resolution_fields_by_intent",
    )
    intents = shape(
        acceptance["required_resolution_fields_by_intent"],
        " ".join(intent.value for intent in PrimaryIntent),
    )
    return InputMeaningPolicy(
        _execution(data["execution"]),
        InputMeaningAcceptancePolicy(
            _text(acceptance["policy_id"]), _integer(acceptance["policy_revision"]),
            _number(acceptance["clarification_confidence_threshold"]),
            {
                PrimaryIntent(key): tuple(_text(field) for field in _sequence(fields))
                for key, fields in intents.items()
            },
        ),
    )


def _lane(value: object) -> RuntimeLanePolicy:
    data = shape(
        value,
        "lane_id queue_capacity queue_policy max_in_flight cancellation_grace_seconds error_isolation",
    )
    return RuntimeLanePolicy(
        _text(data["lane_id"]), _integer(data["queue_capacity"]),
        QueuePolicy(_text(data["queue_policy"])), _integer(data["max_in_flight"]),
        _number(data["cancellation_grace_seconds"]),
        LaneErrorPolicy(_text(data["error_isolation"])),
    )


def _config_ref(value: object) -> ConfigurationReference:
    data = shape(value, "resource_ref config_id config_revision")
    return ConfigurationReference(
        resource(data["resource_ref"]),
        identity(data["config_id"]),
        revision(data["config_revision"]),
    )


def load_core_config(source: str | bytes) -> CoreConfig:
    data = shape(
        parse(source),
        "schema_id config_id config_revision activation_id composition_id "
        "composition_revision appraisal_config executive_config attention_policy "
        "provider_deployment character_definition input_meaning scheduler integration shutdown",
    )
    attention = shape(data["attention_policy"], "policy_id policy_revision")
    provider = shape(data["provider_deployment"], "resource_ref deployment_id deployment_revision")
    character = shape(data["character_definition"], "resource_ref character_id definition_revision")
    scheduler = shape(data["scheduler"], "policy_id policy_revision max_priority_burst")
    integration = shape(data["integration"], "policy_id policy_revision lane_policies")
    shutdown_data = shape(
        data["shutdown"],
        "policy_id policy_revision in_flight_settle_grace_seconds "
        "final_persistence_grace_seconds resource_close_grace_seconds owned_task_join_grace_seconds",
    )
    shutdown = RuntimeShutdownPolicy(
        _text(shutdown_data["policy_id"]), _integer(shutdown_data["policy_revision"]),
        _number(shutdown_data["in_flight_settle_grace_seconds"]),
        _number(shutdown_data["final_persistence_grace_seconds"]),
        _number(shutdown_data["resource_close_grace_seconds"]),
        _number(shutdown_data["owned_task_join_grace_seconds"]),
    )
    scheduler_policy = RuntimeSchedulerPolicy(
        _text(scheduler["policy_id"]), _integer(scheduler["policy_revision"]),
        _integer(scheduler["max_priority_burst"]),
    )
    integration_policy = BrainIntegrationRuntimePolicy(
        _text(integration["policy_id"]), _integer(integration["policy_revision"]), scheduler_policy,
        tuple(_lane(lane) for lane in _sequence(integration["lane_policies"])), shutdown,
    )
    return CoreConfig(
        identity(data["schema_id"]),
        identity(data["config_id"]),
        revision(data["config_revision"]),
        identity(data["activation_id"]),
        identity(data["composition_id"]),
        revision(data["composition_revision"]),
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
        _meaning(data["input_meaning"]),
        scheduler_policy,
        integration_policy,
        shutdown,
    )
