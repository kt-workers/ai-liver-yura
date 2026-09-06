"""定型の状況評価から状態更新への引渡しと本番の拒否判断を確認する。"""

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from app.domain.appraisal import (
    DeterministicAppraisalRule,
    InternalStateSnapshot,
    StateDeltaProposal,
)
from app.subsystems.validation.contracts import Gate, LabMode, RunStatus, ValidationRunResult
from app.subsystems.validation.fast_appraisal import FastAppraisalCase, fast_appraisal_target
from app.subsystems.validation.runtime import ValidationRunner
from tests.domain.appraisal import test_appraisal_paths as domain
from tests.subsystems.validation.json_values import value_at
from tests.subsystems.validation.test_runtime import FIXTURE, POLICY, PROVENANCE, spec


def case(
    *,
    rules: tuple[DeterministicAppraisalRule, ...] | None = None,
    state: InternalStateSnapshot | None = None,
    current_source_context_revision: int = 7,
    committed_at: datetime | None = None,
) -> FastAppraisalCase:
    rule = DeterministicAppraisalRule(
        "rule:activity",
        "activity.completed",
        (),
        (StateDeltaProposal(domain.JOY, 0.2, 0.9, ("seed",)),),
        0.7,
        0.8,
    )
    item = FastAppraisalCase(
        FIXTURE,
        domain.event(),
        domain.state() if state is None else state,
        (rule,) if rules is None else rules,
        current_source_context_revision,
        domain.NOW + timedelta(seconds=1),
        domain.NOW + timedelta(seconds=2) if committed_at is None else committed_at,
    )
    return replace(item, fixture=replace(item.fixture, typed_inputs=item.typed_inputs()))


async def run(item: FastAppraisalCase, *, repeat_count: int = 1) -> ValidationRunResult:
    runner = ValidationRunner((fast_appraisal_target((item,), PROVENANCE, "1"),), POLICY)
    result = await runner.run(
        replace(
            spec(), target_module="fast_appraisal", mode=LabMode.ADJACENT, repeat_count=repeat_count
        ),
        item.fixture,
    )
    assert runner.pending_count == 0
    return result


@pytest.mark.asyncio
async def test_fast_candidate_reaches_real_reducer_and_repeats_are_isolated() -> None:
    item = case()
    result = await run(item, repeat_count=2)
    assert result.status is RunStatus.COMPLETED and result.machine_gate is Gate.NOT_RUN
    for stage in result.stage_results:
        value = stage.typed_outputs
        assert value_at(value, "before", "revision") == 3
        assert value_at(value, "after", "revision") == 4
        assert value_at(value, "after", "facets", 0, "current") == pytest.approx(0.4)
        assert value_at(value, "candidate", "source_event_ids") == (item.event.event_id,)
        causes = value_at(value, "candidate", "proposals", 0, "cause_refs")
        assert causes == (item.event.event_id, "rule:activity")
        assert value_at(value, "after", "facets", 0, "cause_refs") == causes
    assert item.state.revision == 3 and item.state.facets[0].current == 0.2
    assert [x.stage for x in result.timeline].count("appraisal.state_commit") == 2


@pytest.mark.asyncio
async def test_event_without_rule_produces_no_candidate_or_state_commit() -> None:
    result = await run(case(rules=()))
    value = result.stage_results[0].typed_outputs
    assert value_at(value, "candidate") is None and value_at(value, "before") == value_at(
        value, "after"
    )
    assert not any(x.stage == "appraisal.state_commit" for x in result.timeline)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "item",
    [
        case(current_source_context_revision=8),
        case(state=domain.state(value=0.9)),
        case(committed_at=domain.NOW),
    ],
)
async def test_actual_reducer_rejects_stale_context_overflow_or_old_commit_time(
    item: FastAppraisalCase,
) -> None:
    result = await run(item)
    assert result.status is RunStatus.PRODUCT_FAILED
    assert any(
        x.stage == "appraisal.state_commit" and x.status is RunStatus.PRODUCT_FAILED
        for x in result.timeline
    )


@pytest.mark.asyncio
async def test_adjacent_proof_cannot_be_relabelled_integrated() -> None:
    item = case()
    runner = ValidationRunner((fast_appraisal_target((item,), PROVENANCE, "1"),), POLICY)
    result = await runner.run(
        replace(spec(), target_module="fast_appraisal", mode=LabMode.INTEGRATED), item.fixture
    )
    assert result.status is RunStatus.BLOCKED_UPSTREAM and result.timeline == ()
