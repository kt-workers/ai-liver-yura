"""同じ発話所有者で待ち行列・再照合・提示・取消を確認する。"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace

import pytest

from app.domain.speech_runtime.contracts import (
    CandidateLifecycle,
    PreparedSpeechCandidate,
    SpeechPresentationCommand,
    SpeechPresentationCommitState,
    SpeechPresentationReport,
    SpeechPresentationReportStatus,
)
from app.domain.speech_runtime.discard import PreparedAudioDiscardRequest
from app.domain.speech_runtime.policy import SpeechCandidatePriority
from app.subsystems.validation.contracts import LabMode, LabRunSpec, RunStatus
from app.subsystems.validation.runtime import ValidationRunner
from app.subsystems.validation.speech_queue import SpeechQueueCase, speech_queue_target
from tests.subsystems.validation.json_values import value_at
from tests.subsystems.validation.test_runtime import FIXTURE, POLICY, PROVENANCE, spec
from tests.subsystems.validation.test_speech_presentation import case as presentation_case
from tests.subsystems.validation.test_speech_presentation import report


class Connections:
    def __init__(self, *, block: bool = False) -> None:
        self.commands: list[SpeechPresentationCommand] = []
        self.discarded: list[PreparedAudioDiscardRequest] = []
        self.started, self.release, self.closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
        self.stale = False
        if not block:
            self.release.set()

    async def current_state(
        self, candidate: PreparedSpeechCandidate
    ) -> SpeechPresentationCommitState:
        return replace(
            presentation_case().state,
            source_context_revision=candidate.source_context_revision + int(self.stale),
        )

    async def present(
        self, command: SpeechPresentationCommand
    ) -> AsyncIterator[SpeechPresentationReport]:
        self.commands.append(command)
        self.started.set()
        try:
            yield replace(
                report(command, SpeechPresentationReportStatus.STARTED, command.committed_at),
                audio_ref=command.audio_ref,
            )
            await self.release.wait()
            yield replace(
                report(command, SpeechPresentationReportStatus.COMPLETED, command.committed_at),
                audio_ref=command.audio_ref,
            )
        finally:
            self.closed.set()

    async def discard(self, request: PreparedAudioDiscardRequest) -> None:
        self.discarded.append(request)


def case(*, capacity: int = 4) -> SpeechQueueCase:
    source = presentation_case()
    candidates = tuple(
        replace(
            source,
            candidate=replace(
                source.candidate,
                candidate_id=f"candidate-{i}",
                lifecycle=CandidateLifecycle.PREPARED,
                priority=priority,
            ),
            policy=replace(source.policy, prepared_queue_capacity=capacity),
        )
        for i, priority in enumerate(
            (SpeechCandidatePriority.BACKGROUND, SpeechCandidatePriority.FOREGROUND)
        )
    )
    item = SpeechQueueCase(FIXTURE, candidates)
    return replace(item, fixture=replace(FIXTURE, typed_inputs=item.typed_inputs()))


def run_spec(*, repeat_count: int = 1) -> LabRunSpec:
    return replace(
        spec(), target_module="speech_queue", mode=LabMode.ADJACENT, repeat_count=repeat_count
    )


def runner(item: SpeechQueueCase, connections: Connections) -> ValidationRunner:
    return ValidationRunner(
        (
            speech_queue_target(
                (item,),
                connections,
                connections.present,
                connections,
                PROVENANCE,
                "1",
            ),
        ),
        replace(POLICY, max_intervals=80, max_tasks=32),
    )


@pytest.mark.asyncio
async def test_priority_order_and_repeat_identity_use_same_runtime_queue() -> None:
    item, connections = case(), Connections()
    result = await runner(item, connections).run(run_spec(repeat_count=2), item.fixture)
    assert result.status is RunStatus.COMPLETED
    assert [x.candidate_id.rsplit(":", 1)[-1] for x in connections.commands] == [
        "candidate-1",
        "candidate-0",
        "candidate-1",
        "candidate-0",
    ]
    assert len({x.candidate_id for x in connections.commands}) == 4
    for stage in result.stage_results:
        assert value_at(stage.typed_outputs, "queue_count") == 0
        for i in range(2):
            assert value_at(stage.typed_outputs, "candidates", i, "lifecycle") == "completed"


@pytest.mark.asyncio
async def test_state_change_during_first_presentation_rejects_waiting_candidate() -> None:
    item, connections = case(), Connections(block=True)
    lab = runner(item, connections)
    task = asyncio.create_task(lab.run(run_spec(), item.fixture))
    await asyncio.wait_for(connections.started.wait(), 1)
    connections.stale = True
    connections.release.set()
    result = await task
    assert result.status is RunStatus.PRODUCT_FAILED and len(connections.commands) == 1
    assert value_at(result.stage_results[0].typed_outputs, "revalidation_failed") is not None
    assert (
        value_at(
            result.stage_results[0].typed_outputs, "presentations", 0, "candidate", "lifecycle"
        )
        == "completed"
    )


@pytest.mark.asyncio
async def test_overflow_does_not_present_rejected_candidate() -> None:
    item, connections = case(capacity=1), Connections()
    result = await runner(item, connections).run(run_spec(), item.fixture)
    assert result.status is RunStatus.COMPLETED and len(connections.commands) == 1
    assert (
        value_at(result.stage_results[0].typed_outputs, "candidates", 1, "lifecycle")
        == "superseded"
    )


@pytest.mark.asyncio
async def test_cancel_closes_current_presentation_and_never_starts_waiting_candidate() -> None:
    item, connections = case(), Connections(block=True)
    lab = runner(item, connections)
    task = asyncio.create_task(lab.run(run_spec(), item.fixture))
    await asyncio.wait_for(connections.started.wait(), 1)
    await lab.cancel(run_spec().run_id)
    result = await task
    assert result.status is RunStatus.CANCELLED
    assert connections.closed.is_set() and len(connections.commands) == 1 and lab.pending_count == 0


def test_duplicate_and_unprepared_inputs_are_rejected() -> None:
    item = case()
    with pytest.raises(ValueError, match="異なる"):
        replace(item, candidates=(item.candidates[0], item.candidates[0]))
    with pytest.raises(ValueError, match="準備済み"):
        replace(item, candidates=(presentation_case(), item.candidates[1]))


@pytest.mark.asyncio
async def test_changed_fixture_never_starts_presentation() -> None:
    item, connections = case(), Connections()
    result = await runner(item, connections).run(
        run_spec(),
        replace(item.fixture, typed_inputs={"changed": True}),
    )
    assert result.status is RunStatus.BLOCKED_UPSTREAM and connections.commands == []


@pytest.mark.asyncio
async def test_cancel_discards_audio_of_current_and_waiting_candidates() -> None:
    from app.domain.speech_runtime.contracts import AudioReadinessState

    item, connections = case(), Connections(block=True)
    item = replace(
        item,
        candidates=tuple(
            replace(
                x,
                candidate=replace(
                    x.candidate,
                    prepared_audio_ref=f"audio:{x.candidate.candidate_id}",
                    readiness=replace(x.candidate.readiness, audio=AudioReadinessState.READY),
                ),
            )
            for x in item.candidates
        ),
    )
    item = replace(item, fixture=replace(item.fixture, typed_inputs=item.typed_inputs()))
    lab = runner(item, connections)
    task = asyncio.create_task(lab.run(run_spec(), item.fixture))
    await asyncio.wait_for(connections.started.wait(), 1)
    await lab.cancel(run_spec().run_id)
    result = await task
    assert result.status is RunStatus.CANCELLED
    assert {x.audio_ref for x in connections.discarded} == {
        "audio:candidate-0",
        "audio:candidate-1",
    }
    assert connections.closed.is_set() and lab.pending_count == 0


@pytest.mark.asyncio
async def test_failed_audio_discard_does_not_skip_remaining_candidate_cleanup() -> None:
    from app.domain.speech_runtime.contracts import AudioReadinessState

    class FailingDiscard(Connections):
        async def discard(self, request: PreparedAudioDiscardRequest) -> None:
            self.discarded.append(request)
            if len(self.discarded) == 1:
                raise RuntimeError("外部破棄接続の非公開詳細")

    item, connections = case(), FailingDiscard(block=True)
    item = replace(
        item,
        candidates=tuple(
            replace(
                x,
                candidate=replace(
                    x.candidate,
                    prepared_audio_ref=f"audio:{x.candidate.candidate_id}",
                    readiness=replace(x.candidate.readiness, audio=AudioReadinessState.READY),
                ),
            )
            for x in item.candidates
        ),
    )
    item = replace(item, fixture=replace(item.fixture, typed_inputs=item.typed_inputs()))
    lab = runner(item, connections)
    task = asyncio.create_task(lab.run(run_spec(), item.fixture))
    await asyncio.wait_for(connections.started.wait(), 1)
    await lab.cancel(run_spec().run_id)
    result = await task
    assert result.status is RunStatus.HARNESS_FAILED
    assert {x.audio_ref for x in connections.discarded} == {
        "audio:candidate-0",
        "audio:candidate-1",
    }
    assert connections.closed.is_set() and lab.pending_count == 0
    assert "外部破棄接続の非公開詳細" not in result.export_json(1000000)
