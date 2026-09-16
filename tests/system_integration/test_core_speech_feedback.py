"""production Supervisorからの実reportを、Owner受理後に還流する。"""

import asyncio
from dataclasses import replace

import pytest

from app.composition.execution_observation import SPEECH_OBSERVATION_POLICY
from app.composition.speech_feedback import CoreSpeechFeedback, ObservedSpeechPresentationBoundary
from app.domain.activity_execution import ActivityExecutionAuthority
from app.domain.activity_execution.observation import ObservedExecutionFactRecord
from app.domain.contracts import ExecutionStatus
from app.domain.speech_runtime.presentation import SpeechPresentationExecutor
from app.domain.speech_runtime.runtime import SpeechRuntime
from app.domain.speech_runtime.tasks import CandidateTaskRegistry
from tests.domain.speech_runtime.policy_fixtures import runtime_policy
from tests.domain.speech_runtime.test_presentation import _ready_candidate, _state
from tests.infrastructure.speech_presentation.test_process import boundary, policy
from tests.system_integration.test_execution_observation_boundary import PROVENANCE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,expected",
    [
        ("normal", (ExecutionStatus.OBSERVABLE, ExecutionStatus.COMPLETED)),
        ("failed_before", ()),
        ("failed_after", (ExecutionStatus.OBSERVABLE, ExecutionStatus.FAILED)),
        ("hang", (ExecutionStatus.OBSERVABLE, ExecutionStatus.FAILED)),
    ],
)
async def test_accepted_process_reports_reach_fact_owner(
    kind: str, expected: tuple[ExecutionStatus, ...]
) -> None:
    runtime = SpeechRuntime(replace(runtime_policy(), presentation_timeout=policy()))
    tasks = CandidateTaskRegistry()
    authority = ActivityExecutionAuthority(observation_policy=SPEECH_OBSERVATION_POLICY)
    delivered: list[ObservedExecutionFactRecord] = []
    feedback = CoreSpeechFeedback(runtime, authority, "presentation", PROVENANCE, delivered.append)
    supervisor = boundary(kind)
    observed = ObservedSpeechPresentationBoundary(supervisor, feedback)
    await runtime.register(_ready_candidate())
    await SpeechPresentationExecutor(runtime, tasks).commit_and_present(
        candidate_id="candidate", state=_state(), presentation_id="presentation", adapter=observed
    )

    async def finished() -> None:
        while tasks.pending_task_count:
            await asyncio.sleep(0.001)

    try:
        await asyncio.wait_for(finished(), 4)
        assert tuple(r.result.status for r in delivered) == expected
        if delivered:
            assert delivered[-1].effects == delivered[0].effects
            assert delivered[-1].result.effect_refs == delivered[0].result.effect_refs
        await feedback.publish()
        assert len(delivered) == len(expected)
        assert supervisor.active_execution_count == 0
    finally:
        await tasks.shutdown()


@pytest.mark.asyncio
async def test_feedback_failure_retries_same_owner_record_without_duplicate_effect() -> None:
    from tests.system_integration.test_execution_observation_boundary import presentation

    runtime, command, report = await presentation()
    await runtime.accept_report(report)
    authority = ActivityExecutionAuthority(observation_policy=SPEECH_OBSERVATION_POLICY)
    attempts: list[ObservedExecutionFactRecord] = []

    def deliver(record: ObservedExecutionFactRecord) -> None:
        attempts.append(record)
        if len(attempts) == 1:
            raise ValueError("下流受付失敗の注入")

    feedback = CoreSpeechFeedback(runtime, authority, command.presentation_id, PROVENANCE, deliver)
    with pytest.raises(ValueError, match="下流受付失敗"):
        await feedback.publish()
    await feedback.publish()
    await feedback.publish()
    assert len(attempts) == 2
    assert attempts[0] == attempts[1]
    assert attempts[1].record_revision == 1
