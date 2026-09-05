"""本番データの読込と、構成境界での拒否を検証する。"""

from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from app.config.minimum_brain import load_minimum_brain_config
from app.domain.brain_integration import BrainIntegrationLane, BrainIntegrationModule
from app.domain.input_meaning import PrimaryIntent
from app.domain.llm import LLMModelClass, LLMReasoningEffort
from app.runtime.kernel import LaneErrorPolicy, QueuePolicy

RESOURCE = Path(__file__).resolve().parents[2] / "resources/config/v2/minimum_brain.yaml"


def test_canonical_resource_and_shared_policy_instances() -> None:
    config = load_minimum_brain_config(RESOURCE.read_bytes())
    assert config.schema_id == "yura.minimum-brain.production-config.v1"
    assert config.config_id == "yura.minimum-brain.production"
    assert config.config_revision == 1
    assert config.character_definition_path == "resources/character_definitions/v2/yura.yaml"
    assert config.brain_module_registrations == (BrainIntegrationModule.INPUT_MEANING,)
    acceptance = config.input_meaning_policy.acceptance
    assert (acceptance.policy_id, acceptance.policy_revision) == (
        "yura.input-meaning.acceptance",
        1,
    )
    assert acceptance.clarification_confidence_threshold == 0.70
    assert dict(acceptance.required_resolution_fields_by_intent) == {
        PrimaryIntent.PROVIDE_INFORMATION: ("information",),
        PrimaryIntent.REQUEST_INFORMATION: (),
        PrimaryIntent.REQUEST_ACTION: ("target_ref",),
        PrimaryIntent.CONFIRM: ("references",),
        PrimaryIntent.DENY: ("references",),
        PrimaryIntent.START_ACTIVITY: ("target_ref",),
        PrimaryIntent.STOP_ACTIVITY: ("target_ref",),
        PrimaryIntent.ASK_INTERNAL_STATE: ("target_ref",),
        PrimaryIntent.SOCIAL: (),
        PrimaryIntent.OTHER: (),
    }
    execution = config.input_meaning_policy.execution
    assert (execution.policy_id, execution.policy_revision) == ("yura.input-meaning.execution", 1)
    assert execution.model_class is LLMModelClass.BALANCED
    assert execution.reasoning_effort is LLMReasoningEffort.MEDIUM
    assert (execution.timeout_seconds, execution.max_attempts, execution.max_output_tokens) == (
        10,
        1,
        800,
    )
    assert execution.temperature_normalized is None
    assert execution.retry_policy.to_dict() == {
        "initial_backoff_seconds": 1.0,
        "backoff_multiplier": 1.0,
        "max_backoff_seconds": 1.0,
    }
    assert config.integration_policy.scheduler_policy is config.scheduler_policy
    assert config.integration_policy.shutdown_policy is config.shutdown_policy
    assert (
        config.scheduler_policy.policy_id,
        config.scheduler_policy.policy_revision,
        config.scheduler_policy.max_priority_burst,
    ) == ("yura.minimum-brain.scheduler", 1, 8)
    assert (config.integration_policy.policy_id, config.integration_policy.policy_revision) == (
        "yura.minimum-brain.integration",
        1,
    )
    lanes = config.integration_policy.lane_policies
    assert {lane.lane_id for lane in lanes} == {lane.value for lane in BrainIntegrationLane}
    assert [(lane.lane_id, lane.queue_capacity, lane.max_in_flight) for lane in lanes] == [
        ("foreground_interaction", 64, 4),
        ("cognitive_normal", 64, 4),
        ("speech_preparation", 32, 2),
        ("background_reflection", 16, 1),
    ]
    assert all(
        lane.queue_policy is QueuePolicy.REJECT_NEW
        and lane.error_isolation is LaneErrorPolicy.ISOLATE
        and lane.cancellation_grace_seconds == 0.5
        for lane in lanes
    )
    stop = config.shutdown_policy
    assert (stop.policy_id, stop.policy_revision) == ("yura.minimum-brain.shutdown", 1)
    assert (
        stop.in_flight_settle_grace_seconds,
        stop.final_persistence_grace_seconds,
        stop.resource_close_grace_seconds,
        stop.owned_task_join_grace_seconds,
    ) == (2, 0, 2, 2)
    with pytest.raises(FrozenInstanceError):
        cast(Any, config).config_revision = 2
    with pytest.raises(TypeError):
        acceptance.required_resolution_fields_by_intent[PrimaryIntent.SOCIAL] = ("target_ref",)  # type: ignore[index]


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("schema_id",), "unknown"),
        (("config_id",), "unknown"),
        (("config_revision",), True),
        (("config_revision",), 0),
        (("config_revision",), -1),
        (("config_revision",), "1"),
        (("character_definition_path",), ""),
        (("brain_module_registrations",), ["input_meaning", "input_meaning"]),
        (("brain_module_registrations",), ["executive"]),
        (("brain_module_registrations",), ["unknown"]),
        (("brain_module_registrations",), []),
        (("brain_module_registrations",), "input_meaning"),
        (("input_meaning", "execution", "model_class"), "BALANCED"),
        (("input_meaning", "execution", "reasoning_effort"), "unknown"),
        (("input_meaning", "execution", "timeout_seconds"), True),
        (("input_meaning", "execution", "timeout_seconds"), 0),
        (("input_meaning", "execution", "timeout_seconds"), float("nan")),
        (("input_meaning", "execution", "max_attempts"), False),
        (("input_meaning", "execution", "max_output_tokens"), -1),
        (("input_meaning", "execution", "temperature_normalized"), 2),
        (("input_meaning", "execution", "retry_policy", "initial_backoff_seconds"), 0),
        (("input_meaning", "execution", "retry_policy", "backoff_multiplier"), 0.5),
        (("input_meaning", "execution", "retry_policy", "max_backoff_seconds"), 0.5),
        (("input_meaning", "acceptance", "clarification_confidence_threshold"), True),
        (("input_meaning", "acceptance", "clarification_confidence_threshold"), 1.1),
        (
            ("input_meaning", "acceptance", "required_resolution_fields_by_intent", "social"),
            ["unknown"],
        ),
        (
            ("input_meaning", "acceptance", "required_resolution_fields_by_intent", "social"),
            ["references", "references"],
        ),
        (("scheduler", "max_priority_burst"), 0),
        (("scheduler", "policy_revision"), True),
        (("integration", "lane_policies", 0, "queue_capacity"), True),
        (("integration", "lane_policies", 0, "max_in_flight"), 0),
        (("integration", "lane_policies", 0, "queue_policy"), "unknown"),
        (("integration", "lane_policies", 0, "error_isolation"), "unknown"),
        (("integration", "lane_policies", 0, "lane_id"), "unknown"),
        (("integration", "lane_policies", 0, "cancellation_grace_seconds"), -0.1),
        (("shutdown", "owned_task_join_grace_seconds"), float("inf")),
        (("shutdown", "resource_close_grace_seconds"), True),
    ],
)
def test_invalid_values_are_not_coerced(path: tuple[str | int, ...], value: object) -> None:
    data: Any = yaml.safe_load(RESOURCE.read_text())
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError, match="本番設定"):
        load_minimum_brain_config(yaml.safe_dump(data))


@pytest.mark.parametrize(
    "path",
    [
        (),
        ("input_meaning",),
        ("input_meaning", "execution"),
        ("input_meaning", "execution", "retry_policy"),
        ("input_meaning", "acceptance"),
        ("input_meaning", "acceptance", "required_resolution_fields_by_intent"),
        ("scheduler",),
        ("integration",),
        ("integration", "lane_policies", 0),
        ("shutdown",),
    ],
)
@pytest.mark.parametrize("mutation", ["missing", "unknown"])
def test_exact_fields_at_every_level(path: tuple[str | int, ...], mutation: str) -> None:
    data: Any = yaml.safe_load(RESOURCE.read_text())
    target = data
    for key in path:
        target = target[key]
    if mutation == "missing":
        del target[next(iter(target))]
    else:
        target["未定義の項目"] = "試験用"
    with pytest.raises(ValueError):
        load_minimum_brain_config(yaml.safe_dump(data))


@pytest.mark.parametrize(
    "fragment",
    [
        "schema_id: duplicate\n",
        "scheduler:\n  policy_id: duplicate\n",
    ],
)
def test_duplicate_top_level_keys(fragment: str) -> None:
    with pytest.raises(ValueError):
        load_minimum_brain_config(RESOURCE.read_text() + fragment)


@pytest.mark.parametrize(
    "line",
    [
        "    policy_id: yura.input-meaning.execution",
        "      backoff_multiplier: 1.0",
        "      social: []",
        "      queue_capacity: 64",
    ],
)
def test_duplicate_nested_keys(line: str) -> None:
    source = RESOURCE.read_text().replace(line, line + "\n" + line, 1)
    with pytest.raises(ValueError):
        load_minimum_brain_config(source)


@pytest.mark.parametrize("case", ["missing", "duplicate"])
def test_lane_coverage(case: str) -> None:
    data = yaml.safe_load(RESOURCE.read_text())
    lanes = data["integration"]["lane_policies"]
    if case == "missing":
        lanes.pop()
    else:
        lanes[-1] = lanes[0]
    with pytest.raises(ValueError):
        load_minimum_brain_config(yaml.safe_dump(data))


@pytest.mark.parametrize("source", ["[", "", "[]", "1: invalid", "!!python/object:invalid {}"])
def test_malformed_or_non_mapping_yaml(source: str) -> None:
    with pytest.raises(ValueError) as caught:
        load_minimum_brain_config(source)
    assert str(caught.value) == "最小Brainの本番設定を読み込めません"
