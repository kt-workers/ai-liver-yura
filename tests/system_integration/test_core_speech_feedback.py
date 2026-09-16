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


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["retry", "submit", "generation", "capacity", "integrity"])
async def test_downstream_failure_preserves_actual_process_terminal(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from typing import Any

    from app.composition.input_reference_context import CoreInputReferenceContextBinding
    from app.composition.presentation_notification import CorePresentationNotification
    from app.composition.speech_feedback import SpeechFactDeliveryDisposition as Delivery
    from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY as BOUNDS
    from app.domain.contracts import CapabilityAvailability
    from app.domain.goals import GoalCommitmentStore
    from app.domain.input_gateway import InputPermission, InputSourceState
    from app.domain.speech_runtime.contracts import CandidateLifecycle
    from app.usecases.attention import AttentionResponseSettlementCoordinator
    from tests.domain.attention.test_attention_response_settlement import prepared_store
    from tests.domain.attention.test_attention_turn_store import signal
    from tests.domain.input_meaning.test_input_meaning import policy as meaning_policy
    from tests.system_integration.test_presentation_notification import (
        GoalSnapshotSource,
        Normalizer,
        Submitted,
    )

    runtime = SpeechRuntime(replace(runtime_policy(), presentation_timeout=policy()))
    tasks = CandidateTaskRegistry()
    owner = ActivityExecutionAuthority(observation_policy=SPEECH_OBSERVATION_POLICY)
    attention = prepared_store()
    goals = GoalSnapshotSource(32)
    reference = CoreInputReferenceContextBinding(
        goals if failure == "capacity" else GoalCommitmentStore(), owner, meaning_policy(), BOUNDS
    )
    before_reference = reference.snapshot()
    normalizer = Normalizer()
    admissions: list[Any] = []

    def submit(admission: Any, root: str) -> Any:
        admissions.append(admission)
        if failure == "submit" and len(admissions) == 1:
            raise ValueError("一時的な同期受付失敗")
        return Submitted()

    notification = CorePresentationNotification(
        owner,
        attention,
        reference,
        normalizer,
        InputSourceState(
            "speech", "subsystem", CapabilityAvailability.AVAILABLE, InputPermission.NOT_REQUIRED
        ),
        PROVENANCE,
        "root",
        "presentation",
        submit,
    )
    attempts: list[ObservedExecutionFactRecord] = []

    def deliver(record: ObservedExecutionFactRecord) -> Delivery:
        attempts.append(record)
        if failure == "integrity":
            raise ValueError("試験用のprovenance矛盾")
        if failure == "retry" and len(attempts) == 1:
            return Delivery.RETRY
        return notification.deliver(record)

    prepare = AttentionResponseSettlementCoordinator.prepare
    races = 0

    def prepare_with_race(self: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal races
        request = prepare(self, *args, **kwargs)
        if failure == "generation" and races == 0:
            races += 1
            attention.offer(signal("racing-source", seconds=30))
        return request

    monkeypatch.setattr(AttentionResponseSettlementCoordinator, "prepare", prepare_with_race)
    feedback = CoreSpeechFeedback(runtime, owner, "presentation", PROVENANCE, deliver)
    supervisor = boundary("normal")

    def disposition() -> Delivery | None:
        return feedback.disposition

    open_session = supervisor.open
    second_receive, release = asyncio.Event(), asyncio.Event()

    class GateSession:
        def __init__(self, session: Any) -> None:
            self.session = session
            self.received = 0

        async def receive(self) -> Any:
            self.received += 1
            if self.received == 2:
                second_receive.set()
                await release.wait()
            return await self.session.receive()

        async def close(self) -> None:
            await self.session.close()

    # 実workerの2件目reportの読取時機だけを制御し、reportを生成・改変しない。
    monkeypatch.setattr(supervisor, "open", lambda c, p: GateSession(open_session(c, p)))
    await runtime.register(_ready_candidate())
    await SpeechPresentationExecutor(runtime, tasks).commit_and_present(
        candidate_id="candidate",
        state=_state(),
        presentation_id="presentation",
        adapter=ObservedSpeechPresentationBoundary(supervisor, feedback),
    )
    try:
        await asyncio.wait_for(second_receive.wait(), 3)
        assert (await runtime.candidate("candidate")).lifecycle is CandidateLifecycle.PRESENTING
        initial = owner.observed_snapshot("speech-presentation-report", "presentation").value
        assert initial is not None and initial.result.status is ExecutionStatus.OBSERVABLE
        if failure in ("retry", "submit", "capacity"):
            assert disposition() is Delivery.RETRY
            assert feedback._delivered_revision == 0
        if failure in ("retry", "submit"):
            await feedback.publish()
            assert attempts[0] is attempts[1]
            assert feedback._delivered_revision == initial.record_revision
        if failure == "submit":
            assert admissions[0] is admissions[1]
            assert normalizer.calls == 1
        if failure == "integrity":
            assert disposition() is Delivery.INTEGRITY_ERROR
            assert isinstance(feedback.integration_error, ValueError)
            with pytest.raises(ValueError, match="provenance"):
                await feedback.publish()
        release.set()

        async def finished() -> None:
            while tasks.pending_task_count:
                await asyncio.sleep(0.001)

        await asyncio.wait_for(finished(), 3)
        assert (await runtime.candidate("candidate")).lifecycle is CandidateLifecycle.COMPLETED
        final = owner.observed_snapshot("speech-presentation-report", "presentation").value
        assert final is not None and final.result.status is ExecutionStatus.COMPLETED
        assert final.effects == initial.effects
        assert final.result.effect_refs == initial.result.effect_refs
        assert len(final.result.effect_refs) == 1
        assert supervisor.active_execution_count == 0
        if failure in ("generation", "capacity"):
            assert disposition() is Delivery.RETRY
            assert feedback._delivered_revision < final.record_revision
            if failure == "capacity":
                assert reference.snapshot() is before_reference
                assert normalizer.calls == 0
                goals.value = replace(goals.value, revision=33, goals=goals.value.goals[:-1])
            await feedback.publish()
            assert disposition() is Delivery.DELIVERED
            assert feedback._delivered_revision == final.record_revision
        if failure == "integrity":
            assert disposition() is Delivery.INTEGRITY_ERROR
            assert isinstance(feedback.integration_error, ValueError)
            assert feedback._delivered_revision == 0
        else:
            count = len(attempts)
            await feedback.publish()
            assert len(attempts) == count
    finally:
        release.set()
        await tasks.shutdown()
