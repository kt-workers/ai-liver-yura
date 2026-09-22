"""本番の提示前照合、結果受入れ、取消時の提示処理回収を確認する。"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import datetime

import pytest

from app.domain.speech_runtime.contracts import (
    SpeechPresentationCommand,
    SpeechPresentationMode,
    SpeechPresentationReport,
    SpeechPresentationReportStatus,
)
from app.subsystems.validation.contracts import Gate, LabRunSpec, RunStatus
from app.subsystems.validation.runtime import ValidationRunner
from app.subsystems.validation.speech_presentation import (
    SpeechPresentationCase,
    speech_presentation_target,
)
from tests.domain.speech_runtime import test_presentation as product
from tests.subsystems.validation.json_values import array_at, value_at
from tests.subsystems.validation.test_runtime import FIXTURE, POLICY, PROVENANCE, spec


def case() -> SpeechPresentationCase:
    candidate, state = product._ready_candidate(), product._state()
    item = SpeechPresentationCase(FIXTURE, candidate, state, product._TEST_POLICY)
    return replace(item, fixture=replace(FIXTURE, typed_inputs=item.typed_inputs()))


def run_spec(*, repeat_count: int = 1) -> LabRunSpec:
    return replace(spec(), target_module="speech_presentation", repeat_count=repeat_count)


def report(
    command: SpeechPresentationCommand, status: SpeechPresentationReportStatus, now: datetime
) -> SpeechPresentationReport:
    return SpeechPresentationReport(
        presentation_id=command.presentation_id,
        candidate_id=command.candidate_id,
        status=status,
        output_modes=(SpeechPresentationMode.TEXT_ONLY,),
        started_at=now,
        completed_at=now if status is SpeechPresentationReportStatus.COMPLETED else None,
        audio_ref=None,
        timing_ref=None,
    )


@pytest.mark.asyncio
async def test_actual_runtime_accepts_terminal_report_and_preserves_repeat_identity() -> None:
    item = case()
    calls = []

    async def adapter(
        command: SpeechPresentationCommand,
    ) -> AsyncIterator[SpeechPresentationReport]:
        calls.append(command)
        yield report(command, SpeechPresentationReportStatus.STARTED, item.state.observed_at)
        yield report(command, SpeechPresentationReportStatus.COMPLETED, item.state.observed_at)

    runner = ValidationRunner(
        (speech_presentation_target((item,), adapter, PROVENANCE, "1"),), POLICY
    )
    result = await runner.run(run_spec(repeat_count=2), item.fixture)
    assert result.status is RunStatus.COMPLETED and result.machine_gate is Gate.NOT_RUN
    assert len({c.candidate_id for c in calls}) == 2
    for stage in result.stage_results:
        assert value_at(stage.typed_outputs, "candidate", "lifecycle") == "completed"
        assert value_at(stage.typed_outputs, "terminal_reports", 0, "status") == "completed"
        assert [
            value_at(r, "status") for r in array_at(stage.typed_outputs, "accepted_reports")
        ] == [
            "started",
            "completed",
        ]
    assert runner.pending_count == 0


@pytest.mark.asyncio
async def test_rejected_acceptance_never_calls_presentation_adapter() -> None:
    item = case()
    item = replace(item, state=replace(item.state, semantic_acceptance_id="different"))
    item = replace(item, fixture=replace(item.fixture, typed_inputs=item.typed_inputs()))
    calls = []

    async def adapter(
        command: SpeechPresentationCommand,
    ) -> AsyncIterator[SpeechPresentationReport]:
        calls.append(command)
        yield report(command, SpeechPresentationReportStatus.COMPLETED, item.state.observed_at)

    runner = ValidationRunner(
        (speech_presentation_target((item,), adapter, PROVENANCE, "1"),), POLICY
    )
    result = await runner.run(run_spec(), item.fixture)
    assert result.status is RunStatus.PRODUCT_FAILED and calls == []


@pytest.mark.asyncio
async def test_nonterminal_stream_is_not_recorded_as_completed() -> None:
    item = case()

    async def adapter(
        command: SpeechPresentationCommand,
    ) -> AsyncIterator[SpeechPresentationReport]:
        yield report(command, SpeechPresentationReportStatus.STARTED, item.state.observed_at)

    runner = ValidationRunner(
        (speech_presentation_target((item,), adapter, PROVENANCE, "1"),), POLICY
    )
    result = await runner.run(run_spec(), item.fixture)
    assert result.status is RunStatus.PRODUCT_FAILED
    assert runner.pending_count == 0


@pytest.mark.asyncio
async def test_cancel_closes_presentation_stream() -> None:
    item = case()
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def adapter(
        command: SpeechPresentationCommand,
    ) -> AsyncIterator[SpeechPresentationReport]:
        yield report(command, SpeechPresentationReportStatus.STARTED, item.state.observed_at)
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    runner = ValidationRunner(
        (speech_presentation_target((item,), adapter, PROVENANCE, "1"),), POLICY
    )
    task = asyncio.create_task(runner.run(run_spec(), item.fixture))
    await asyncio.wait_for(started.wait(), 0.5)
    await runner.cancel(run_spec().run_id)
    result = await task
    assert result.status is RunStatus.CANCELLED
    assert cancelled.is_set() and runner.pending_count == 0
