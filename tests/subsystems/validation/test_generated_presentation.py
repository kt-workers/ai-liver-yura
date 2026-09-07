"""実際の生成・採用結果から同じ候補を提示完了まで継続する。"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace

import pytest

from app.domain.speech_runtime.contracts import (
    PreparedSpeechCandidate,
    SpeechPresentationCommand,
    SpeechPresentationCommitState,
    SpeechPresentationMode,
    SpeechPresentationReport,
    SpeechPresentationReportStatus,
)
from app.subsystems.validation.contracts import Gate, RunStatus
from app.subsystems.validation.speech_preparation import SpeechPreparationSettings
from tests.domain.speech_runtime import test_presentation as product
from tests.subsystems.validation import test_speech_presentation as presentation
from tests.subsystems.validation.json_values import value_at
from tests.subsystems.validation.test_speech_generation import setup
from tests.subsystems.validation.test_speech_generation_chain import Verification, chain_spec
from tests.subsystems.validation.test_speech_preparation import settings


class Live:
    async def current_state(
        self, candidate: PreparedSpeechCandidate
    ) -> SpeechPresentationCommitState:
        return replace(
            product._state(),
            source_context_revision=candidate.source_context_revision,
            goal_revision=candidate.goal_revision,
            attention_revision=candidate.attention_revision,
            semantic_acceptance_id=candidate.semantic_acceptance_id,
            performance_plan_id=candidate.performance_plan_id,
        )


def configuration() -> SpeechPreparationSettings:
    return replace(
        settings(),
        queue_for_revalidation=True,
        validate_for_presentation=True,
        present_after_validation=True,
        presentation_modes=(SpeechPresentationMode.TEXT_ONLY,),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("accepted", [False, True])
async def test_generated_candidate_is_presented_only_after_real_acceptance(accepted: bool) -> None:
    calls = []

    async def adapter(
        command: SpeechPresentationCommand,
    ) -> AsyncIterator[SpeechPresentationReport]:
        calls.append(command)
        yield presentation.report(
            command,
            SpeechPresentationReportStatus.STARTED,
            command.committed_at,
        )
        yield presentation.report(
            command,
            SpeechPresentationReportStatus.COMPLETED,
            command.committed_at,
        )

    verification = Verification(accepted=accepted)
    item, runner, _, _ = setup(
        verifier=verification.build,
        preparation=configuration(),
        revalidation=Live(),
        presentation=adapter,
    )
    result = await runner.run(chain_spec(), item.fixture)
    assert result.status is RunStatus.COMPLETED and result.machine_gate is Gate.NOT_RUN
    output = result.stage_results[0].typed_outputs
    prepared = value_at(output, "evaluation", "prepared_candidate")
    if accepted:
        assert value_at(prepared, "candidate", "lifecycle") == "completed"
        assert calls[0].candidate_id == value_at(prepared, "candidate", "candidate_id")
        assert calls[0].utterance_id == value_at(output, "utterance", "utterance_id")
        assert value_at(prepared, "candidate", "speech_plan_id") == value_at(
            output, "semantic_plan", "plan_id"
        )
    else:
        assert value_at(prepared, "lifecycle") == "rejected" and calls == []
    assert runner.pending_count == 0


@pytest.mark.asyncio
async def test_cancel_during_presentation_closes_generated_candidate_work() -> None:
    started, stopped = asyncio.Event(), asyncio.Event()

    async def adapter(
        command: SpeechPresentationCommand,
    ) -> AsyncIterator[SpeechPresentationReport]:
        yield presentation.report(
            command,
            SpeechPresentationReportStatus.STARTED,
            command.committed_at,
        )
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    item, runner, _, _ = setup(
        verifier=Verification(accepted=True).build,
        preparation=configuration(),
        revalidation=Live(),
        presentation=adapter,
    )
    task = asyncio.create_task(runner.run(chain_spec(), item.fixture))
    await asyncio.wait_for(started.wait(), 0.5)
    await runner.cancel(chain_spec().run_id)
    result = await task
    assert result.status is RunStatus.CANCELLED
    assert stopped.is_set() and runner.pending_count == 0
