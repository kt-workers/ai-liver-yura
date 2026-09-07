"""最小Brainの本番設定を検証し、不変な構成へ変換する。"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

import yaml
from yaml.nodes import MappingNode

from app.domain.brain_integration import BrainIntegrationModule, BrainIntegrationRuntimePolicy
from app.domain.input_meaning import InputMeaningAcceptancePolicy, InputMeaningPolicy, PrimaryIntent
from app.domain.llm import (
    LLMExecutionPolicy,
    LLMModelClass,
    LLMReasoningEffort,
    LLMRequestRetryPolicy,
)
from app.runtime.kernel import (
    LaneErrorPolicy,
    QueuePolicy,
    RuntimeLanePolicy,
    RuntimeSchedulerPolicy,
)
from app.runtime.shutdown import RuntimeShutdownPolicy


@dataclass(frozen=True, slots=True)
class MinimumBrainProductionConfig:
    """読み込んだ一世代の設定。ドメイン状態の正本にはしない。"""

    schema_id: str
    config_id: str
    config_revision: int
    character_definition_path: str
    brain_module_registrations: tuple[BrainIntegrationModule, ...]
    input_meaning_policy: InputMeaningPolicy
    scheduler_policy: RuntimeSchedulerPolicy
    integration_policy: BrainIntegrationRuntimePolicy
    shutdown_policy: RuntimeShutdownPolicy


class _StrictLoader(yaml.SafeLoader):
    pass


def _unique_mapping(
    loader: _StrictLoader,
    node: MappingNode,
    deep: bool = False,
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result:
            raise ValueError("設定の項目名が不正または重複しています")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def _mapping(value: object, fields: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != set(fields.split()):
        raise ValueError("設定の項目が不足しているか未定義の項目があります")
    return {str(key): item for key, item in value.items()}


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("設定には空でない文字列が必要です")
    return value


def _integer(value: object) -> int:
    if type(value) is not int:
        raise ValueError("設定には整数が必要です")
    return value


def _number(value: object) -> float:
    if type(value) not in (int, float) or not isinstance(value, (int, float)):
        raise ValueError("設定には数値が必要です")
    if not isfinite(value):
        raise ValueError("設定には有限の数値が必要です")
    return float(value)


def _sequence(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("設定には配列が必要です")
    return list(value)


def _execution(value: object) -> LLMExecutionPolicy:
    data = _mapping(
        value,
        "policy_id policy_revision model_class reasoning_effort timeout_seconds "
        "max_attempts max_output_tokens temperature_normalized retry_policy",
    )
    retry = _mapping(
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
    data = _mapping(value, "acceptance execution")
    acceptance = _mapping(
        data["acceptance"],
        "policy_id policy_revision "
        "clarification_confidence_threshold required_resolution_fields_by_intent",
    )
    intents = _mapping(
        acceptance["required_resolution_fields_by_intent"],
        " ".join(intent.value for intent in PrimaryIntent),
    )
    return InputMeaningPolicy(
        _execution(data["execution"]),
        InputMeaningAcceptancePolicy(
            _text(acceptance["policy_id"]),
            _integer(acceptance["policy_revision"]),
            _number(acceptance["clarification_confidence_threshold"]),
            {
                PrimaryIntent(key): tuple(_text(field) for field in _sequence(fields))
                for key, fields in intents.items()
            },
        ),
    )


def _lane(value: object) -> RuntimeLanePolicy:
    data = _mapping(
        value,
        "lane_id queue_capacity queue_policy max_in_flight "
        "cancellation_grace_seconds error_isolation",
    )
    return RuntimeLanePolicy(
        _text(data["lane_id"]),
        _integer(data["queue_capacity"]),
        QueuePolicy(_text(data["queue_policy"])),
        _integer(data["max_in_flight"]),
        _number(data["cancellation_grace_seconds"]),
        LaneErrorPolicy(_text(data["error_isolation"])),
    )


def _build(value: object) -> MinimumBrainProductionConfig:
    data = _mapping(
        value,
        "schema_id config_id config_revision character_definition_path "
        "brain_module_registrations input_meaning scheduler integration shutdown",
    )
    schema_id, config_id = _text(data["schema_id"]), _text(data["config_id"])
    revision = _integer(data["config_revision"])
    if (
        schema_id != "yura.minimum-brain.production-config.v1"
        or config_id != "yura.minimum-brain.production"
        or revision < 1
    ):
        raise ValueError("設定の識別子または版が不正です")
    modules = tuple(
        BrainIntegrationModule(_text(item))
        for item in _sequence(data["brain_module_registrations"])
    )
    if modules != (BrainIntegrationModule.INPUT_MEANING,):
        raise ValueError("早期起動の登録は入力意味解析1件でなければなりません")
    shutdown_data = _mapping(
        data["shutdown"],
        "policy_id policy_revision "
        "in_flight_settle_grace_seconds final_persistence_grace_seconds "
        "resource_close_grace_seconds owned_task_join_grace_seconds",
    )
    shutdown = RuntimeShutdownPolicy(
        _text(shutdown_data["policy_id"]),
        _integer(shutdown_data["policy_revision"]),
        _number(shutdown_data["in_flight_settle_grace_seconds"]),
        _number(shutdown_data["final_persistence_grace_seconds"]),
        _number(shutdown_data["resource_close_grace_seconds"]),
        _number(shutdown_data["owned_task_join_grace_seconds"]),
    )
    scheduler_data = _mapping(data["scheduler"], "policy_id policy_revision max_priority_burst")
    scheduler = RuntimeSchedulerPolicy(
        _text(scheduler_data["policy_id"]),
        _integer(scheduler_data["policy_revision"]),
        _integer(scheduler_data["max_priority_burst"]),
    )
    integration_data = _mapping(data["integration"], "policy_id policy_revision lane_policies")
    integration = BrainIntegrationRuntimePolicy(
        _text(integration_data["policy_id"]),
        _integer(integration_data["policy_revision"]),
        scheduler,
        tuple(_lane(lane) for lane in _sequence(integration_data["lane_policies"])),
        shutdown,
    )
    return MinimumBrainProductionConfig(
        schema_id,
        config_id,
        revision,
        _text(data["character_definition_path"]),
        modules,
        _meaning(data["input_meaning"]),
        scheduler,
        integration,
        shutdown,
    )


def load_minimum_brain_config(source: str | bytes) -> MinimumBrainProductionConfig:
    """入力値を例外へ露出せず、不正な設定は補完せずに拒否する。"""
    try:
        return _build(yaml.load(source, Loader=_StrictLoader))
    except (yaml.YAMLError, ValueError, TypeError, OverflowError):
        raise ValueError("最小Brainの本番設定を読み込めません") from None
