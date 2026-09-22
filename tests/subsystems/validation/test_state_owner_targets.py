"""局所的な目標・約束の更新と注意の引渡しを製品の入口で確認する。"""

import json
from dataclasses import replace

import pytest

from app.domain.attention import AttentionSchedulingPolicy
from app.domain.executive import CommitmentTransitionOperation, GoalTransitionOperation
from app.domain.goals import GoalCommitmentStore
from app.subsystems.validation.contracts import RunStatus
from app.subsystems.validation.runtime import ValidationRunner
from app.subsystems.validation.state_owners import (
    AttentionLabCase,
    AttentionLabStep,
    GoalCommitmentLabCase,
    attention_target,
    goal_commitment_target,
)
from tests.domain.attention import test_attention_turn_store as attention
from tests.domain.goals import test_goal_commitment_store as goals
from tests.subsystems.validation.test_runtime import FIXTURE, POLICY, PROVENANCE, spec


def goal_case() -> GoalCommitmentLabCase:
    first = goals.decision(
        "create-goal", 0, goals=(goals.goal_transition(GoalTransitionOperation.CREATE, 0),)
    )
    second = goals.decision(
        "create-commitment",
        1,
        commitments=(goals.commitment_transition(CommitmentTransitionOperation.CREATE, 1),),
    )
    item = GoalCommitmentLabCase(FIXTURE, GoalCommitmentStore().snapshot(), (first, second))
    return replace(item, fixture=replace(FIXTURE, typed_inputs=item.typed_inputs()))


@pytest.mark.asyncio
async def test_goals_and_commitments_are_applied_only_to_fresh_local_store() -> None:
    item = goal_case()
    target = goal_commitment_target((item,), PROVENANCE, "1")
    result = await ValidationRunner((target,), POLICY).run(
        replace(spec(), target_module="goal_commitment", repeat_count=2),
        item.fixture,
    )
    assert result.status is RunStatus.COMPLETED
    stages = json.loads(result.export_json(POLICY.max_export_bytes))["stage_results"]
    for stage in stages:
        state = stage["typed_outputs"]["final_snapshot"]
        assert state["revision"] == 2
        assert len(state["goals"]) == len(state["commitments"]) == 1
        assert len(stage["typed_outputs"]["commits"]) == 2
    assert item.initial.revision == 0 and not item.initial.goals


@pytest.mark.asyncio
async def test_repeated_decision_is_rejected_by_real_store() -> None:
    item = goal_case()
    item = replace(item, decisions=(item.decisions[0], item.decisions[0]))
    item = replace(item, fixture=replace(item.fixture, typed_inputs=item.typed_inputs()))
    target = goal_commitment_target((item,), PROVENANCE, "1")
    result = await ValidationRunner((target,), POLICY).run(
        replace(spec(), target_module="goal_commitment"),
        item.fixture,
    )
    assert result.status is RunStatus.PRODUCT_FAILED


@pytest.mark.asyncio
async def test_attention_coordinator_hands_off_actual_claim_per_repeat() -> None:
    signal = attention.signal("activity-completed")
    item = AttentionLabCase(
        FIXTURE,
        (AttentionLabStep(signal, 2, signal.occurred_at),),
        AttentionSchedulingPolicy.production(),
    )
    item = replace(item, fixture=replace(FIXTURE, typed_inputs=item.typed_inputs()))
    target = attention_target((item,), PROVENANCE, "1")
    result = await ValidationRunner((target,), POLICY).run(
        replace(spec(), target_module="attention", repeat_count=2),
        item.fixture,
    )
    assert result.status is RunStatus.COMPLETED
    stages = json.loads(result.export_json(POLICY.max_export_bytes))["stage_results"]
    for stage in stages:
        output = stage["typed_outputs"]
        assert len(output["enqueued_triggers"]) == 1
        assert output["steps"][0]["claimed"] == output["enqueued_triggers"][0]


@pytest.mark.asyncio
async def test_goal_and_commitment_changes_reach_attention_with_distinct_context_revision() -> None:
    from app.subsystems.validation.contracts import LabMode
    from app.subsystems.validation.state_owners import GoalAttentionLabSettings
    from tests.subsystems.validation.json_values import array_at, integer_at, value_at

    item = goal_case()
    item = replace(
        item, attention=GoalAttentionLabSettings(AttentionSchedulingPolicy.production(), (41, 42))
    )
    item = replace(item, fixture=replace(FIXTURE, typed_inputs=item.typed_inputs()))
    result = await ValidationRunner(
        (goal_commitment_target((item,), PROVENANCE, "1"),), POLICY
    ).run(
        replace(spec(), target_module="goal_commitment", mode=LabMode.ADJACENT, repeat_count=2),
        item.fixture,
    )
    assert result.status is RunStatus.COMPLETED
    for stage in result.stage_results:
        steps = array_at(stage.typed_outputs, "attention_steps")
        assert len(steps) == 2
        assert [integer_at(step, "signal", "source_context_revision") for step in steps] == [41, 42]
        assert [value_at(step, "signal", "source_kind") for step in steps] == ["goal", "commitment"]
        for step in steps:
            assert value_at(step, "signal", "source_revision") == value_at(
                step, "fact", "source_revision"
            )
        assert integer_at(stage.typed_outputs, "final_snapshot", "revision") == 2
    assert item.initial.revision == 0


@pytest.mark.asyncio
async def test_goal_activation_and_completion_use_owner_refresh_and_resolve() -> None:
    from app.subsystems.validation.contracts import LabMode
    from app.subsystems.validation.state_owners import GoalAttentionLabSettings
    from tests.subsystems.validation.json_values import array_at, value_at

    operations = (
        GoalTransitionOperation.CREATE,
        GoalTransitionOperation.ACTIVATE,
        GoalTransitionOperation.COMPLETE,
    )
    decisions = tuple(
        goals.decision(f"step-{index}", index, goals=(goals.goal_transition(operation, index),))
        for index, operation in enumerate(operations)
    )
    item = GoalCommitmentLabCase(
        FIXTURE,
        GoalCommitmentStore().snapshot(),
        decisions,
        GoalAttentionLabSettings(AttentionSchedulingPolicy.production(), (50, 51, 52)),
    )
    item = replace(item, fixture=replace(FIXTURE, typed_inputs=item.typed_inputs()))
    result = await ValidationRunner(
        (goal_commitment_target((item,), PROVENANCE, "1"),), POLICY
    ).run(replace(spec(), target_module="goal_commitment", mode=LabMode.ADJACENT), item.fixture)
    assert result.status is RunStatus.COMPLETED
    steps = array_at(result.stage_results[0].typed_outputs, "attention_steps")
    assert [value_at(step, "signal", "operation") for step in steps] == [
        "offer",
        "refresh",
        "resolve",
    ]
    assert array_at(steps[-1], "snapshot", "sources") == ()
    assert value_at(steps[-1], "signal", "expected_source_revision") == value_at(
        steps[-2], "fact", "source_revision"
    )


@pytest.mark.asyncio
async def test_rejected_goal_update_does_not_reach_attention_again() -> None:
    from app.subsystems.validation.contracts import LabMode
    from app.subsystems.validation.state_owners import GoalAttentionLabSettings

    item = goal_case()
    item = replace(
        item,
        decisions=(item.decisions[0], item.decisions[0]),
        attention=GoalAttentionLabSettings(AttentionSchedulingPolicy.production(), (50, 51)),
    )
    item = replace(item, fixture=replace(FIXTURE, typed_inputs=item.typed_inputs()))
    result = await ValidationRunner(
        (goal_commitment_target((item,), PROVENANCE, "1"),), POLICY
    ).run(replace(spec(), target_module="goal_commitment", mode=LabMode.ADJACENT), item.fixture)
    assert result.status is RunStatus.PRODUCT_FAILED
    assert sum(interval.stage == "goals.attention.handle" for interval in result.timeline) == 1


def test_goal_attention_requires_context_revision_for_every_commit() -> None:
    from app.subsystems.validation.state_owners import GoalAttentionLabSettings

    with pytest.raises(ValueError, match="各更新"):
        replace(
            goal_case(),
            attention=GoalAttentionLabSettings(AttentionSchedulingPolicy.production(), (1,)),
        )


@pytest.mark.asyncio
async def test_fulfilled_commitment_is_removed_from_attention_by_owner_fact() -> None:
    from app.subsystems.validation.contracts import LabMode
    from app.subsystems.validation.state_owners import GoalAttentionLabSettings
    from tests.subsystems.validation.json_values import array_at, value_at

    item = goal_case()
    extra = tuple(
        goals.decision(
            f"commitment-step-{revision}",
            revision,
            commitments=(goals.commitment_transition(operation, revision),),
        )
        for revision, operation in (
            (2, CommitmentTransitionOperation.ACTIVATE),
            (3, CommitmentTransitionOperation.FULFILL),
        )
    )
    item = replace(
        item,
        decisions=item.decisions + extra,
        attention=GoalAttentionLabSettings(
            AttentionSchedulingPolicy.production(), (60, 61, 62, 63)
        ),
    )
    item = replace(item, fixture=replace(FIXTURE, typed_inputs=item.typed_inputs()))
    result = await ValidationRunner(
        (goal_commitment_target((item,), PROVENANCE, "1"),), POLICY
    ).run(replace(spec(), target_module="goal_commitment", mode=LabMode.ADJACENT), item.fixture)
    assert result.status is RunStatus.COMPLETED
    steps = array_at(result.stage_results[0].typed_outputs, "attention_steps")
    assert [value_at(step, "signal", "operation") for step in steps[1:]] == [
        "offer",
        "refresh",
        "resolve",
    ]
    resolved = value_at(steps[-1], "signal", "source_ref")
    assert resolved not in {
        value_at(source, "source_ref") for source in array_at(steps[-1], "snapshot", "sources")
    }
