"""本番データを正本として読み、設定不備が補完されないことを確認する。"""

from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from app.config.executive import (
    ExecutiveConfigurationError,
    load_executive_config,
    read_executive_config,
)
from app.config.executive import (
    ExecutiveConfigurationFailureCode as Code,
)
from app.domain.executive import ExecutiveIntentKind, RequirementMode, RequirementSelectorField

SOURCE = Path("resources/config/v2/executive.yaml").read_text()


def data() -> dict[str, Any]:
    return cast(dict[str, Any], yaml.safe_load(SOURCE))


def test_production_values_and_exact_rules() -> None:
    config = load_executive_config(SOURCE.encode())
    assert (config.schema_id, config.config_id, config.config_revision) == (
        "yura.executive.production-config.v1",
        "yura.executive.production",
        1,
    )
    assert config.execution.to_dict() == {
        "policy_id": "yura.executive.execution",
        "policy_revision": 1,
        "model_class": "balanced",
        "reasoning_effort": "medium",
        "timeout_seconds": 20.0,
        "max_attempts": 1,
        "max_output_tokens": 4096,
        "temperature_normalized": None,
        "retry_policy": {
            "initial_backoff_seconds": 1.0,
            "backoff_multiplier": 2.0,
            "max_backoff_seconds": 4.0,
        },
    }
    assert (config.requirements.policy_id, config.requirements.revision) == (
        "yura.executive.requirements",
        1,
    )
    assert len(config.requirements.rules) == 6
    assert {r.intent_kind for r in config.requirements.rules} == set(ExecutiveIntentKind)
    for rule in config.requirements.rules:
        assert rule.rule_id == "executive.requirements.production." + rule.intent_kind.value
        assert (rule.revision, rule.policy_id, rule.policy_revision) == (
            1,
            config.requirements.policy_id,
            1,
        )
        assert (rule.selector.field, rule.selector.value) == (RequirementSelectorField.KIND, None)
        assert rule.capabilities == ()
        assert rule.preconditions == ()
        if rule.intent_kind is ExecutiveIntentKind.ACTIVITY:
            assert rule.mode is RequirementMode.UPSTREAM
            assert rule.source is not None
        elif rule.intent_kind is ExecutiveIntentKind.PLAN_EXECUTION:
            assert rule.mode is RequirementMode.PLAN_SCOPE and rule.source is None
        else:
            assert rule.mode is RequirementMode.CONSTANT and rule.source is None
    assert config.direct_records == ()
    assert config.direct_route_id == "executive.requirements.production.direct"
    with pytest.raises(FrozenInstanceError):
        cast(Any, config).config_revision = 2
    with pytest.raises(FrozenInstanceError):
        cast(Any, config.execution).max_attempts = 5
    assert read_executive_config(Path("resources/config/v2/executive.yaml")) == config


@pytest.mark.parametrize(
    "section,field,value",
    [
        ("", "schema_id", "unknown"),
        ("", "config_id", "test.llm.execution"),
        ("", "config_revision", True),
        ("", "config_revision", 0),
        ("execution", "policy_id", ""),
        ("execution", "policy_id", "test.llm.execution"),
        ("execution", "policy_revision", -1),
        ("execution", "policy_revision", 0),
        ("execution", "policy_revision", True),
        ("execution", "model_class", "unknown"),
        ("execution", "reasoning_effort", "unknown"),
        ("execution", "timeout_seconds", True),
        ("execution", "timeout_seconds", 0),
        ("execution", "timeout_seconds", float("nan")),
        ("execution", "timeout_seconds", float("inf")),
        ("execution", "timeout_seconds", "20"),
        ("execution", "max_attempts", True),
        ("execution", "max_attempts", 0),
        ("execution", "max_attempts", 1.1),
        ("execution", "max_output_tokens", True),
        ("execution", "max_output_tokens", -1),
        ("execution", "temperature_normalized", True),
        ("execution", "temperature_normalized", 1.1),
        ("execution", "temperature_normalized", float("nan")),
        ("requirements", "policy_id", "other"),
        ("requirements", "revision", True),
        ("requirements", "revision", 0),
        ("direct_activity", "route_id", "unknown"),
        ("direct_activity", "records", None),
        ("retry", "initial_backoff_seconds", 0),
        ("retry", "initial_backoff_seconds", True),
        ("retry", "backoff_multiplier", 0.9),
        ("retry", "backoff_multiplier", float("inf")),
        ("retry", "max_backoff_seconds", 0.5),
        ("retry", "max_backoff_seconds", True),
    ],
)
def test_invalid_values_fail_closed(section: str, field: str, value: object) -> None:
    raw = data()
    target = (
        raw["execution"]["retry_policy"] if section == "retry" else raw[section] if section else raw
    )
    target[field] = value
    with pytest.raises(ExecutiveConfigurationError):
        load_executive_config(yaml.safe_dump(raw))


@pytest.mark.parametrize(
    "section", ["", "execution", "requirements", "direct_activity", "retry", "rule", "selector"]
)
@pytest.mark.parametrize("operation", ["missing", "unknown"])
def test_closed_shapes(section: str, operation: str) -> None:
    raw = data()
    target = (
        raw["execution"]["retry_policy"]
        if section == "retry"
        else raw["requirements"]["rules"][0]["selector"]
        if section == "selector"
        else raw["requirements"]["rules"][0]
        if section == "rule"
        else raw[section]
        if section
        else raw
    )
    if operation == "missing":
        del target[next(iter(target))]
    else:
        target["private-unexpected"] = "private-value"
    with pytest.raises(ExecutiveConfigurationError) as caught:
        load_executive_config(yaml.safe_dump(raw))
    assert "private-" not in str(caught.value)


@pytest.mark.parametrize(
    "source",
    [
        "schema_id: x\nschema_id: y",
        "1: value",
        "execution: [",
        "!!python/object:private.Class {}",
        "&root {child: *root}",
        "&root [*root]",
        "null",
        "[]",
        "!!binary aGVsbG8=",
        SOURCE.replace("max_attempts: 1", "max_attempts: 1\n  max_attempts: 2"),
    ],
)
def test_malformed_duplicate_and_cyclic_yaml(source: str) -> None:
    with pytest.raises(ExecutiveConfigurationError) as caught:
        load_executive_config(source)
    assert caught.value.code in (Code.INVALID_CONFIG, Code.MALFORMED_CONFIG)
    assert "private.Class" not in str(caught.value)
    assert caught.value.__suppress_context__ or caught.value.__context__ is None


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "duplicate",
        "ambiguous",
        "policy",
        "rule_id",
        "revision",
        "selector",
        "mode",
        "nonempty",
        "source",
    ],
)
def test_invalid_rule_sets(change: str) -> None:
    raw = data()
    rules = raw["requirements"]["rules"]
    rule = rules[0]
    if change == "missing":
        rules.pop()
    elif change == "duplicate":
        rules.append(dict(rule))
    elif change == "ambiguous":
        rules[1] = dict(rule, rule_id="another")
    elif change == "policy":
        rule["policy_id"] = "other"
    elif change == "rule_id":
        rule["rule_id"] = "other"
    elif change == "revision":
        rule["revision"] = True
    elif change == "selector":
        rule["selector"]["value"] = "other"
    elif change == "mode":
        rule["mode"] = "upstream"
    elif change == "nonempty":
        rule["capabilities"] = [{"capability_type": "x", "operation": "y", "allow_degraded": False}]
    else:
        rule["source"] = dict(raw["requirements"]["rules"][3]["source"])
    with pytest.raises(ExecutiveConfigurationError):
        load_executive_config(yaml.safe_dump(raw))


def record_data() -> dict[str, Any]:
    return {
        "owner_id": "test-direct-owner",
        "contract_id": "executive.direct-activity-requirements.v1",
        "record_id": "test-direct-record",
        "revision": 1,
        "binding_ref": "binding-1",
        "binding_revision": 1,
        "activity_type": "activity",
        "target_ref": "target",
        "capabilities": [
            {"capability_type": "activity", "operation": "run", "allow_degraded": False}
        ],
        "preconditions": [{"precondition_id": "ready", "expected": {"values": [True, 1]}}],
    }


def test_nested_immutability_and_direct_constructor_validation() -> None:
    raw = data()
    raw["config_revision"] = 2
    raw["direct_activity"]["records"] = [record_data()]
    config = load_executive_config(yaml.safe_dump(raw))
    record = config.direct_records[0]
    value = cast(Any, record.preconditions[0].expected)
    assert value["values"] == (True, 1)
    with pytest.raises(TypeError):
        value["extra"] = 2
    records = [record]
    copied = replace(config, direct_records=cast(Any, records))
    records.clear()
    assert copied.direct_records == (record,)
    with pytest.raises(ExecutiveConfigurationError):
        replace(config, config_revision=True)
    with pytest.raises(ExecutiveConfigurationError):
        replace(config, direct_records=(record, record))
    with pytest.raises(ExecutiveConfigurationError):
        replace(config, execution=cast(Any, None))
    with pytest.raises(ExecutiveConfigurationError):
        replace(
            config, requirements=replace(config.requirements, rules=config.requirements.rules[:-1])
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("contract_id", "unknown"),
        ("revision", True),
        ("binding_revision", -1),
        ("owner_id", ""),
        ("target_ref", 1),
        (
            "capabilities",
            [{"capability_type": "activity", "operation": "run", "allow_degraded": 1}],
        ),
        ("preconditions", [{"precondition_id": "ready", "expected": float("inf")}]),
    ],
)
def test_invalid_direct_record(field: str, value: object) -> None:
    raw = data()
    record = record_data()
    record[field] = value
    raw["direct_activity"]["records"] = [record]
    with pytest.raises(ExecutiveConfigurationError):
        load_executive_config(yaml.safe_dump(raw))


def test_missing_file_diagnostic_is_safe(tmp_path: Path) -> None:
    with pytest.raises(ExecutiveConfigurationError) as caught:
        read_executive_config(tmp_path / "private-setting.yaml")
    assert caught.value.code is Code.MISSING_CONFIG
    assert str(tmp_path) not in str(caught.value)
    assert "private-setting" not in str(caught.value)
