from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from app.config.appraisal import load_appraisal_config

SOURCE = Path("resources/config/v2/appraisal.yaml").read_text()


def test_production_values() -> None:
    config = load_appraisal_config(SOURCE.encode())
    assert (config.schema_id, config.config_id, config.config_revision) == (
        "yura.appraisal.production-config.v1",
        "yura.appraisal.production",
        1,
    )
    assert config.appraisal_policy.execution.to_dict() == {
        "policy_id": "yura.appraisal.execution",
        "policy_revision": 1,
        "model_class": "balanced",
        "reasoning_effort": "medium",
        "timeout_seconds": 15.0,
        "max_attempts": 1,
        "max_output_tokens": 1536,
        "temperature_normalized": None,
        "retry_policy": {
            "initial_backoff_seconds": 0.25,
            "backoff_multiplier": 2.0,
            "max_backoff_seconds": 1.0,
        },
    }
    assert (config.initialization_mode, config.initial_state_revision) == ("fresh_empty", 0)
    assert (config.decay_policy.policy_id, config.decay_policy.policy_revision) == (
        "yura.appraisal.decay",
        1,
    )
    assert [
        (
            r.rule_id,
            r.facet_kind.value,
            r.state_key,
            r.target_scope.value,
            r.neutral_baseline,
            r.half_life_seconds,
            r.minimum_elapsed_seconds,
        )
        for r in config.decay_policy.rules
    ] == [
        (f"{kind}.{scope}", kind, None, scope, 0.0, half, 1.0)
        for kind, half in [("emotion", 300.0), ("arousal", 120.0)]
        for scope in ["global", "targeted"]
    ]
    with pytest.raises(FrozenInstanceError):
        cast(Any, config).config_revision = 2
    with pytest.raises(ValueError):
        replace(config, initial_state_revision=True)


@pytest.mark.parametrize(
    "path,value",
    [
        ("schema_id", "secret-invalid"),
        ("config_id", "bad"),
        ("config_revision", True),
        ("config_revision", -1),
        ("execution.policy_id", "test.llm.execution"),
        ("execution.policy_revision", True),
        ("execution.policy_revision", -1),
        ("execution.model_class", "unknown"),
        ("execution.reasoning_effort", "unknown"),
        ("execution.timeout_seconds", True),
        ("execution.timeout_seconds", float("nan")),
        ("execution.timeout_seconds", float("inf")),
        ("execution.timeout_seconds", 0),
        ("execution.max_attempts", 0),
        ("execution.max_output_tokens", False),
        ("execution.temperature_normalized", float("nan")),
        ("execution.retry_policy", []),
        ("execution.retry_policy.backoff_multiplier", 0.5),
        ("execution.retry_policy.initial_backoff_seconds", False),
        ("execution.retry_policy.max_backoff_seconds", 0.1),
        ("initial_state.mode", "resume"),
        ("initial_state.state_revision", 1),
        ("initial_state.state_revision", False),
        ("decay.policy_id", "bad"),
        ("decay.policy_revision", -1),
        ("decay.rules", {}),
        ("decay.rules.0.facet_kind", "bad"),
        ("decay.rules.0.target_scope", "bad"),
        ("decay.rules.0.neutral_baseline", 2),
        ("decay.rules.0.half_life_seconds", 0),
        ("decay.rules.0.half_life_seconds", float("inf")),
        ("decay.rules.0.minimum_elapsed_seconds", -1),
    ],
)
def test_invalid_values_fail_without_input_disclosure(path: str, value: object) -> None:
    data: Any = yaml.safe_load(SOURCE)
    keys = path.split(".")
    node = data
    for key in keys[:-1]:
        node = node[int(key)] if isinstance(node, list) else node[key]
    node[keys[-1]] = value
    with pytest.raises(ValueError, match="^Appraisalの本番構成を読み込めません$"):
        load_appraisal_config(yaml.safe_dump(data))


@pytest.mark.parametrize(
    "part", ["", "execution", "execution.retry_policy", "initial_state", "decay"]
)
@pytest.mark.parametrize("mode", ["missing", "unknown", "duplicate"])
def test_closed_fields(part: str, mode: str) -> None:
    data: Any = yaml.safe_load(SOURCE)
    node = data
    for key in part.split(".") if part else []:
        node = node[key]
    if mode == "missing":
        node.pop(next(iter(node)))
    elif mode == "unknown":
        node["secret-invalid"] = "secret-invalid"
    serialized = yaml.safe_dump(data)
    if mode == "duplicate":
        key = next(iter(node))
        lines = serialized.splitlines()
        index = next(i for i, line in enumerate(lines) if line.strip().startswith(key + ":"))
        lines.insert(index, lines[index])
        serialized = "\n".join(lines)
    with pytest.raises(ValueError, match="^Appraisalの本番構成を読み込めません$"):
        load_appraisal_config(serialized)


@pytest.mark.parametrize("same_id", [True, False])
def test_duplicate_decay_selector_or_id(same_id: bool) -> None:
    data = yaml.safe_load(SOURCE)
    rule = dict(data["decay"]["rules"][0])
    if not same_id:
        rule["rule_id"] = "another"
    data["decay"]["rules"].append(rule)
    with pytest.raises(ValueError):
        load_appraisal_config(yaml.safe_dump(data))
