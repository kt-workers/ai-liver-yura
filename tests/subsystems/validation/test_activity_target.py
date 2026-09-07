"""本番の活動採用・実行結果・効果参照を検証出力まで照合する。"""

from collections.abc import Sequence
from dataclasses import replace
from datetime import timedelta

import pytest

from app.domain.activity_execution import (
    ExecutionAdapterReport,
    ExecutionCancellationSignal,
    ExecutionDispatchRequest,
)
from app.domain.contracts import ExecutionStatus
from app.subsystems.validation.activity import ActivityLabCase, activity_target
from app.subsystems.validation.contracts import RunStatus
from app.subsystems.validation.runtime import ValidationRunner
from tests.domain.activity_execution import test_activity_execution as activity
from tests.subsystems.validation.json_values import array_at, integer_at, value_at
from tests.subsystems.validation.test_runtime import FIXTURE, POLICY, PROVENANCE, spec


class Provider:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    async def execute(
        self, request: ExecutionDispatchRequest, cancellation: ExecutionCancellationSignal
    ) -> Sequence[ExecutionAdapterReport]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("検証用の非公開情報を含む失敗")
        return (
            ExecutionAdapterReport(
                request.invocation.command.command_id,
                request.invocation.invocation_id,
                request.dispatch_id,
                ExecutionStatus.COMPLETED,
                activity.NOW + timedelta(seconds=2),
                {},
                (activity.effect(),),
            ),
        )


def case() -> ActivityLabCase:
    item = ActivityLabCase(
        FIXTURE,
        activity.invocation(),
        (activity.preflight(), activity.preflight()),
        activity.NOW + timedelta(seconds=1),
    )
    return replace(item, fixture=replace(FIXTURE, typed_inputs=item.typed_inputs()))


def runner(item: ActivityLabCase, provider: Provider) -> ValidationRunner:
    return ValidationRunner((activity_target((item,), provider, PROVENANCE, "1", ()),), POLICY)


@pytest.mark.asyncio
async def test_execution_fact_and_event_preserve_actual_effects_per_repeat() -> None:
    item, provider = case(), Provider()
    result = await runner(item, provider).run(
        replace(spec(), target_module="activity_execution", repeat_count=2), item.fixture
    )
    assert result.status is RunStatus.COMPLETED
    assert provider.calls == 2
    for stage in result.stage_results:
        output = stage.typed_outputs
        assert integer_at(output, "preflight_calls") == 2
        assert value_at(output, "record", "result", "status") == "completed"
        assert value_at(output, "event", "payload", "effect_refs") == value_at(
            output, "record", "result", "effect_refs"
        )
        assert array_at(output, "record", "result", "effect_refs")


@pytest.mark.asyncio
async def test_changed_capability_at_second_preflight_prevents_provider_dispatch() -> None:
    item, provider = case(), Provider()
    item = replace(
        item,
        preflight_snapshots=(
            activity.preflight(),
            activity.preflight(capabilities=(activity.capability(revision=3),)),
        ),
    )
    item = replace(item, fixture=replace(FIXTURE, typed_inputs=item.typed_inputs()))
    result = await runner(item, provider).run(
        replace(spec(), target_module="activity_execution"), item.fixture
    )
    assert result.status is RunStatus.COMPLETED
    assert provider.calls == 0
    output = result.stage_results[0].typed_outputs
    assert value_at(output, "record", "result", "status") == "superseded"
    assert not array_at(output, "event", "payload", "effect_refs")


@pytest.mark.asyncio
async def test_provider_exception_keeps_owner_failure_and_uncertainty_without_private_message() -> (
    None
):
    item, provider = case(), Provider(fail=True)
    result = await runner(item, provider).run(
        replace(spec(), target_module="activity_execution"), item.fixture
    )
    assert result.status is RunStatus.COMPLETED
    output = result.stage_results[0].typed_outputs
    assert value_at(output, "record", "result", "status") == "failed"
    assert value_at(output, "event", "payload", "effect_uncertainty") == "unknown"
    assert not array_at(output, "event", "payload", "effect_refs")
    assert "非公開情報" not in result.export_json(POLICY.max_export_bytes)


@pytest.mark.asyncio
async def test_changed_fixture_input_never_dispatches_activity() -> None:
    item, provider = case(), Provider()
    result = await runner(item, provider).run(
        replace(spec(), target_module="activity_execution"),
        replace(item.fixture, typed_inputs={"invocation": "changed"}),
    )
    assert result.status is RunStatus.BLOCKED_UPSTREAM
    assert provider.calls == 0
