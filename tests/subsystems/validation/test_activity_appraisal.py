"""活動の確定出来事から評価と状態更新への由来を照合する。"""

from dataclasses import replace
from datetime import timedelta

import pytest

from app.domain.appraisal import DeterministicAppraisalRule, StateDeltaProposal
from app.subsystems.validation.contracts import LabMode, RunStatus
from app.subsystems.validation.fast_appraisal import EventAppraisalSettings
from tests.domain.activity_execution import test_activity_execution as activity
from tests.domain.appraisal import test_appraisal_paths as appraisal
from tests.subsystems.validation.json_values import value_at
from tests.subsystems.validation.test_activity_target import Provider, case, runner
from tests.subsystems.validation.test_runtime import FIXTURE, spec


def settings(event_type: str = "execution.completed") -> EventAppraisalSettings:
    original = appraisal.state()
    state = replace(
        original,
        updated_at=activity.NOW,
        facets=tuple(replace(facet, updated_at=activity.NOW) for facet in original.facets),
    )
    return EventAppraisalSettings(
        state,
        (
            DeterministicAppraisalRule(
                "rule:test-result",
                event_type,
                (),
                (StateDeltaProposal(appraisal.JOY, 0.2, 0.9, ("fixture",)),),
                0.7,
                0.8,
            ),
        ),
        7,
        activity.NOW + timedelta(seconds=3),
        activity.NOW + timedelta(seconds=4),
    )


@pytest.mark.asyncio
async def test_actual_execution_event_reaches_reducer_with_original_cause_refs() -> None:
    item = replace(case(), appraisal=settings())
    item = replace(item, fixture=replace(FIXTURE, typed_inputs=item.typed_inputs()))
    result = await runner(item, Provider()).run(
        replace(spec(), target_module="activity_execution", mode=LabMode.ADJACENT, repeat_count=2),
        item.fixture,
    )
    assert result.status is RunStatus.COMPLETED
    for stage in result.stage_results:
        output = stage.typed_outputs
        event_id = value_at(output, "event", "event_id")
        assert value_at(output, "appraisal", "candidate", "source_event_ids") == (event_id,)
        assert value_at(output, "appraisal", "after", "facets", 0, "cause_refs") == (
            event_id,
            "rule:test-result",
        )
        assert value_at(output, "appraisal", "after", "revision") == 4
        assert value_at(output, "appraisal", "after", "facets", 0, "current") == pytest.approx(0.4)
    assert item.appraisal is not None and item.appraisal.state.revision == 3


@pytest.mark.asyncio
async def test_failed_execution_does_not_match_success_rule_or_change_state() -> None:
    item = replace(case(), appraisal=settings())
    item = replace(item, fixture=replace(FIXTURE, typed_inputs=item.typed_inputs()))
    result = await runner(item, Provider(fail=True)).run(
        replace(spec(), target_module="activity_execution", mode=LabMode.ADJACENT), item.fixture
    )
    assert result.status is RunStatus.COMPLETED
    output = result.stage_results[0].typed_outputs
    assert value_at(output, "event", "event_type") == "execution.failed"
    assert value_at(output, "event", "payload", "effect_uncertainty") == "unknown"
    assert value_at(output, "appraisal", "candidate") is None
    assert value_at(output, "appraisal", "before") == value_at(output, "appraisal", "after")
    assert not any(x.stage == "appraisal.state_commit" for x in result.timeline)


@pytest.mark.asyncio
async def test_stale_context_rejects_state_commit_after_execution_completes() -> None:
    item = replace(case(), appraisal=replace(settings(), current_source_context_revision=8))
    item = replace(item, fixture=replace(FIXTURE, typed_inputs=item.typed_inputs()))
    provider = Provider()
    result = await runner(item, provider).run(
        replace(spec(), target_module="activity_execution", mode=LabMode.ADJACENT), item.fixture
    )
    assert provider.calls == 1
    assert result.status is RunStatus.PRODUCT_FAILED
    output = result.stage_results[0].typed_outputs
    assert value_at(output, "record", "result", "status") == "completed"
    assert value_at(output, "event", "payload", "effect_refs")
    assert value_at(output, "appraisal_failure_stage") == "appraisal.state_commit"
    assert any(
        x.stage == "activity.execute" and x.status is RunStatus.COMPLETED for x in result.timeline
    )
    assert any(
        x.stage == "appraisal.state_commit" and x.status is RunStatus.PRODUCT_FAILED
        for x in result.timeline
    )
