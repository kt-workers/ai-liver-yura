"""Executiveの本番構成を補完せず、不変なOwner入力へ変換する。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from pathlib import Path
from typing import TypeVar

import yaml
from yaml.nodes import MappingNode

from app.domain.contracts import CapabilityRequirement
from app.domain.contracts.common import freeze_json
from app.domain.executive import (
    DirectActivityRequirementRecord,
    DirectActivityRequirementSourceSpec,
    ExecutiveIntentKind,
    ExecutiveIntentRequirementRule,
    ExecutiveIntentRequirementsPolicy,
    ExecutivePreconditionRequirement,
    RequirementMode,
    RequirementSelector,
    RequirementSelectorField,
)
from app.domain.llm import (
    LLMExecutionPolicy,
    LLMModelClass,
    LLMReasoningEffort,
    LLMRequestRetryPolicy,
)

CONFIG_SOURCE = "resources/config/v2/executive.yaml"
DIRECT_ROUTE = "executive.requirements.production.direct"


class ExecutiveConfigurationFailureCode(str, Enum):
    MALFORMED_CONFIG = "MALFORMED_CONFIG"
    UNSUPPORTED_CONFIG = "UNSUPPORTED_CONFIG"
    INVALID_CONFIG = "INVALID_CONFIG"
    BINDING_MISMATCH = "BINDING_MISMATCH"
    INITIALIZATION_FAILED = "INITIALIZATION_FAILED"
    MISSING_CONFIG = "MISSING_CONFIG"


class ExecutiveConfigurationError(ValueError):
    """入力断片や内部例外を含めない構成失敗。"""

    def __init__(self, code: ExecutiveConfigurationFailureCode) -> None:
        self.code = code
        super().__init__(f"Executive本番構成を使用できません: {code.value}")


def _invalid() -> None:
    raise ExecutiveConfigurationError(ExecutiveConfigurationFailureCode.INVALID_CONFIG)


@dataclass(frozen=True, slots=True)
class ExecutiveProductionConfig:
    schema_id: str
    config_id: str
    config_revision: int
    execution: LLMExecutionPolicy
    requirements: ExecutiveIntentRequirementsPolicy
    direct_route_id: str
    direct_records: tuple[DirectActivityRequirementRecord, ...]

    def __post_init__(self) -> None:
        try:
            self._validate()
        except ExecutiveConfigurationError:
            raise
        except (ValueError, TypeError, AttributeError, RecursionError, OverflowError):
            raise ExecutiveConfigurationError(
                ExecutiveConfigurationFailureCode.INVALID_CONFIG
            ) from None

    def _validate(self) -> None:
        if self.schema_id != "yura.executive.production-config.v1":
            raise ExecutiveConfigurationError(ExecutiveConfigurationFailureCode.UNSUPPORTED_CONFIG)
        if (
            self.config_id != "yura.executive.production"
            or type(self.config_revision) is not int
            or self.config_revision < 1
            or not isinstance(self.execution, LLMExecutionPolicy)
            or not isinstance(self.requirements, ExecutiveIntentRequirementsPolicy)
            or self.direct_route_id != DIRECT_ROUTE
        ):
            _invalid()
        if (
            self.execution.policy_id != "yura.executive.execution"
            or self.execution.policy_revision < 1
            or self.requirements.policy_id != "yura.executive.requirements"
            or self.requirements.revision < 1
        ):
            _invalid()
        rules = self.requirements.rules
        if len(rules) != len(ExecutiveIntentKind) or {r.intent_kind for r in rules} != set(
            ExecutiveIntentKind
        ):
            _invalid()
        for rule in rules:
            mode = RequirementMode.CONSTANT
            source = None
            if rule.intent_kind is ExecutiveIntentKind.ACTIVITY:
                mode = RequirementMode.UPSTREAM
                source = DirectActivityRequirementSourceSpec(self.direct_route_id)
            elif rule.intent_kind is ExecutiveIntentKind.PLAN_EXECUTION:
                mode = RequirementMode.PLAN_SCOPE
            if (
                rule.rule_id != "executive.requirements.production." + rule.intent_kind.value
                or rule.revision < 1
                or rule.policy_id != self.requirements.policy_id
                or rule.policy_revision != self.requirements.revision
                or rule.selector != RequirementSelector(RequirementSelectorField.KIND, None)
                or rule.mode is not mode
                or rule.capabilities
                or rule.preconditions
                or rule.source != source
            ):
                _invalid()
        records = tuple(self.direct_records)
        if any(not isinstance(record, DirectActivityRequirementRecord) for record in records):
            _invalid()
        for field in ("binding_ref", "owner_id", "record_id"):
            if len({getattr(record, field) for record in records}) != len(records):
                _invalid()
        object.__setattr__(self, "direct_records", records)


class _Loader(yaml.SafeLoader):
    """重複キーや暗黙のkey変換を拒否する。"""


def _unique(loader: _Loader, node: MappingNode, deep: bool = False) -> dict[str, object]:
    result: dict[str, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result:
            _invalid()
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique)


def _acyclic(value: object, active: set[int], done: set[int]) -> None:
    if not isinstance(value, (dict, list)):
        return
    identity = id(value)
    if identity in active:
        _invalid()
    if identity in done:
        return
    active.add(identity)
    for item in value.values() if isinstance(value, dict) else value:
        _acyclic(item, active, done)
    active.remove(identity)
    done.add(identity)


def _mapping(value: object, fields: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != set(fields.split()):
        _invalid()
    assert isinstance(value, dict)
    return {str(k): v for k, v in value.items()}


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        _invalid()
    assert isinstance(value, str)
    return value


def _integer(value: object) -> int:
    if type(value) is not int:
        _invalid()
    assert isinstance(value, int)
    return value


def _number(value: object) -> float:
    if type(value) not in (int, float):
        _invalid()
    assert isinstance(value, (int, float))
    result = float(value)
    if not isfinite(result):
        _invalid()
    return result


def _array(value: object) -> list[object]:
    if not isinstance(value, list):
        _invalid()
    assert isinstance(value, list)
    return list(value)


_E = TypeVar("_E", bound=Enum)


def _enum(kind: type[_E], value: object) -> _E:
    try:
        return kind(_text(value))
    except ValueError:
        raise ExecutiveConfigurationError(
            ExecutiveConfigurationFailureCode.UNSUPPORTED_CONFIG
        ) from None


def _capabilities(value: object) -> tuple[CapabilityRequirement, ...]:
    result = []
    for item in _array(value):
        data = _mapping(item, "capability_type operation allow_degraded")
        degraded = data["allow_degraded"]
        if type(degraded) is not bool:
            _invalid()
        assert isinstance(degraded, bool)
        result.append(
            CapabilityRequirement(
                _text(data["capability_type"]), _text(data["operation"]), degraded
            )
        )
    return tuple(result)


def _preconditions(value: object) -> tuple[ExecutivePreconditionRequirement, ...]:
    result = []
    for item in _array(value):
        data = _mapping(item, "precondition_id expected")
        result.append(
            ExecutivePreconditionRequirement(
                _text(data["precondition_id"]), freeze_json(data["expected"])
            )
        )
    return tuple(result)


def _rule(value: object) -> ExecutiveIntentRequirementRule:
    data = _mapping(
        value,
        "rule_id revision policy_id policy_revision intent_kind "
        "selector mode capabilities preconditions source",
    )
    selector = _mapping(data["selector"], "field value")
    source = None
    if data["source"] is not None:
        spec = _mapping(data["source"], "route_id contract_id reference_field")
        source = DirectActivityRequirementSourceSpec(
            _text(spec["route_id"]), _text(spec["contract_id"]), _text(spec["reference_field"])
        )
    return ExecutiveIntentRequirementRule(
        _text(data["rule_id"]),
        _integer(data["revision"]),
        _text(data["policy_id"]),
        _integer(data["policy_revision"]),
        _enum(ExecutiveIntentKind, data["intent_kind"]),
        RequirementSelector(
            _enum(RequirementSelectorField, selector["field"]),
            None if selector["value"] is None else _text(selector["value"]),
        ),
        _enum(RequirementMode, data["mode"]),
        _capabilities(data["capabilities"]),
        _preconditions(data["preconditions"]),
        source,
    )


def _record(value: object) -> DirectActivityRequirementRecord:
    data = _mapping(
        value,
        "owner_id contract_id record_id revision binding_ref binding_revision "
        "activity_type target_ref capabilities preconditions",
    )
    return DirectActivityRequirementRecord(
        _text(data["owner_id"]),
        _text(data["contract_id"]),
        _text(data["record_id"]),
        _integer(data["revision"]),
        _text(data["binding_ref"]),
        _integer(data["binding_revision"]),
        _text(data["activity_type"]),
        None if data["target_ref"] is None else _text(data["target_ref"]),
        _capabilities(data["capabilities"]),
        _preconditions(data["preconditions"]),
    )


def load_executive_config(source: str | bytes) -> ExecutiveProductionConfig:
    """生入力・解析例外を公開せず、本番構成だけを返す。"""
    try:
        raw = yaml.load(source, Loader=_Loader)
        _acyclic(raw, set(), set())
        data = _mapping(
            raw, "schema_id config_id config_revision execution requirements direct_activity"
        )
        execution = _mapping(
            data["execution"],
            "policy_id policy_revision model_class reasoning_effort "
            "timeout_seconds max_attempts max_output_tokens temperature_normalized retry_policy",
        )
        retry = _mapping(
            execution["retry_policy"],
            "initial_backoff_seconds backoff_multiplier max_backoff_seconds",
        )
        requirements = _mapping(data["requirements"], "policy_id revision rules")
        direct = _mapping(data["direct_activity"], "route_id records")
        return ExecutiveProductionConfig(
            _text(data["schema_id"]),
            _text(data["config_id"]),
            _integer(data["config_revision"]),
            LLMExecutionPolicy(
                _text(execution["policy_id"]),
                _integer(execution["policy_revision"]),
                _enum(LLMModelClass, execution["model_class"]),
                _enum(LLMReasoningEffort, execution["reasoning_effort"]),
                _number(execution["timeout_seconds"]),
                _integer(execution["max_attempts"]),
                _integer(execution["max_output_tokens"]),
                LLMRequestRetryPolicy(
                    _number(retry["initial_backoff_seconds"]),
                    _number(retry["backoff_multiplier"]),
                    _number(retry["max_backoff_seconds"]),
                ),
                None
                if execution["temperature_normalized"] is None
                else _number(execution["temperature_normalized"]),
            ),
            ExecutiveIntentRequirementsPolicy(
                _text(requirements["policy_id"]),
                _integer(requirements["revision"]),
                tuple(_rule(rule) for rule in _array(requirements["rules"])),
            ),
            _text(direct["route_id"]),
            tuple(_record(record) for record in _array(direct["records"])),
        )
    except ExecutiveConfigurationError:
        raise
    except (yaml.YAMLError, UnicodeError):
        raise ExecutiveConfigurationError(
            ExecutiveConfigurationFailureCode.MALFORMED_CONFIG
        ) from None
    except (ValueError, TypeError, AttributeError, OverflowError, RecursionError):
        raise ExecutiveConfigurationError(
            ExecutiveConfigurationFailureCode.INVALID_CONFIG
        ) from None


def read_executive_config(path: Path) -> ExecutiveProductionConfig:
    """指定された構成を読む。private pathを公開エラーへ含めない。"""
    try:
        source = path.read_bytes()
    except FileNotFoundError:
        raise ExecutiveConfigurationError(
            ExecutiveConfigurationFailureCode.MISSING_CONFIG
        ) from None
    except OSError:
        raise ExecutiveConfigurationError(
            ExecutiveConfigurationFailureCode.INVALID_CONFIG
        ) from None
    return load_executive_config(source)
