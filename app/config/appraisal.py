"""Appraisalの本番構成を補完せず厳密に読み込む。"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

import yaml
from yaml.nodes import MappingNode

from app.domain.appraisal.contracts import (
    DecayFacetRule,
    DecayPolicy,
    DecayTargetScope,
    StateFacetKind,
)
from app.domain.appraisal.deep import DeepAppraisalPolicy
from app.domain.llm import (
    LLMExecutionPolicy,
    LLMModelClass,
    LLMReasoningEffort,
    LLMRequestRetryPolicy,
)


@dataclass(frozen=True, slots=True)
class AppraisalProductionConfig:
    schema_id: str
    config_id: str
    config_revision: int
    appraisal_policy: DeepAppraisalPolicy
    initialization_mode: str
    initial_state_revision: int
    decay_policy: DecayPolicy

    def __post_init__(self) -> None:
        if (
            self.schema_id != "yura.appraisal.production-config.v1"
            or self.config_id != "yura.appraisal.production"
            or type(self.config_revision) is not int
            or self.config_revision < 1
        ):
            raise ValueError("Appraisal構成の識別子またはリビジョンが不正です")
        if (
            self.initialization_mode != "fresh_empty"
            or type(self.initial_state_revision) is not int
            or self.initial_state_revision != 0
        ):
            raise ValueError("Appraisal初期化方式が不正です")
        if not isinstance(self.appraisal_policy, DeepAppraisalPolicy) or not isinstance(
            self.decay_policy, DecayPolicy
        ):
            raise ValueError("Appraisalと減衰の型付き方針が必要です")
        if (
            self.appraisal_policy.execution.policy_id != "yura.appraisal.execution"
            or self.decay_policy.policy_id != "yura.appraisal.decay"
        ):
            raise ValueError("Appraisal方針の識別子が不正です")


class _Loader(yaml.SafeLoader):
    """重複キーと非文字列キーを拒否する。"""


def _unique(loader: _Loader, node: MappingNode, deep: bool = False) -> dict[str, object]:
    result: dict[str, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result:
            raise ValueError("Appraisal構成のキーが不正です")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique)


def _mapping(value: object, fields: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != set(fields.split()):
        raise ValueError("Appraisal構成の項目が一致しません")
    return {str(k): v for k, v in value.items()}


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Appraisal構成の文字列が不正です")
    return value


def _integer(value: object) -> int:
    if type(value) is not int:
        raise ValueError("Appraisal構成の整数が不正です")
    assert isinstance(value, int)
    return value


def _number(value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError("Appraisal構成の数値が不正です")
    assert isinstance(value, (int, float))
    result = float(value)
    if not isfinite(result):
        raise ValueError("Appraisal構成には有限数が必要です")
    return result


def _rule(value: object) -> DecayFacetRule:
    data = _mapping(
        value,
        "rule_id facet_kind state_key target_scope neutral_baseline "
        "half_life_seconds minimum_elapsed_seconds",
    )
    return DecayFacetRule(
        _text(data["rule_id"]),
        StateFacetKind(_text(data["facet_kind"])),
        None if data["state_key"] is None else _text(data["state_key"]),
        DecayTargetScope(_text(data["target_scope"])),
        _number(data["neutral_baseline"]),
        _number(data["half_life_seconds"]),
        _number(data["minimum_elapsed_seconds"]),
    )


def load_appraisal_config(source: str | bytes) -> AppraisalProductionConfig:
    """解析例外や生入力を公開せず、不変なOwner構成を返す。"""
    try:
        data = _mapping(
            yaml.load(source, Loader=_Loader),
            "schema_id config_id config_revision execution initial_state decay",
        )
        execution = _mapping(
            data["execution"],
            "policy_id policy_revision model_class "
            "reasoning_effort timeout_seconds max_attempts max_output_tokens "
            "temperature_normalized retry_policy",
        )
        retry = _mapping(
            execution["retry_policy"],
            "initial_backoff_seconds backoff_multiplier max_backoff_seconds",
        )
        initial = _mapping(data["initial_state"], "mode state_revision")
        decay = _mapping(data["decay"], "policy_id policy_revision rules")
        rules = decay["rules"]
        if not isinstance(rules, list):
            raise ValueError("減衰規則には配列が必要です")
        return AppraisalProductionConfig(
            _text(data["schema_id"]),
            _text(data["config_id"]),
            _integer(data["config_revision"]),
            DeepAppraisalPolicy(
                LLMExecutionPolicy(
                    _text(execution["policy_id"]),
                    _integer(execution["policy_revision"]),
                    LLMModelClass(_text(execution["model_class"])),
                    LLMReasoningEffort(_text(execution["reasoning_effort"])),
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
                )
            ),
            _text(initial["mode"]),
            _integer(initial["state_revision"]),
            DecayPolicy(
                _text(decay["policy_id"]),
                _integer(decay["policy_revision"]),
                tuple(_rule(rule) for rule in rules),
            ),
        )
    except (yaml.YAMLError, ValueError, TypeError, OverflowError, RecursionError):
        raise ValueError("Appraisalの本番構成を読み込めません") from None
