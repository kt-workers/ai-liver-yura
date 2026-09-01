from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.brain_integration import (
    BrainIntegrationLane,
    BrainIntegrationModule,
    BrainIntegrationRuntime,
    BrainIntegrationRuntimePolicy,
    BrainIntegrationTerminalOutcome,
    BrainIntegrationWork,
    BrainRevisionEvent,
    BrainWorkAdmissionStatus,
    BrainWorkEnvelope,
    BrainWorkPriority,
    BrainWorkStatus,
)
from app.runtime.kernel import (
    CancellationToken,
    FakeRuntimeClock,
    LaneErrorPolicy,
    QueuePolicy,
    RuntimeLanePolicy,
    RuntimeSchedulerPolicy,
)
from app.runtime.shutdown import RuntimeShutdownPolicy

NOW = datetime(2026, 8, 31, tzinfo=timezone.utc)
TEST_SHUTDOWN_POLICY = RuntimeShutdownPolicy("test.brain.shutdown", 1, 1.0, 1.0, 1.0, 1.0)


@dataclass
class FakePort:
    result: object
    fresh: bool = True
    gate: asyncio.Event | None = None
    started: asyncio.Event | None = None
    calls: list[str] = field(default_factory=list)

    def is_fresh(self, work: BrainIntegrationWork) -> bool:
        return self.fresh

    async def execute(
        self,
        work: BrainIntegrationWork,
        cancellation: CancellationToken,
    ) -> object:
        self.calls.append(work.work_id)
        if self.started is not None:
            self.started.set()
        if self.gate is not None:
            await self.gate.wait()
        return self.result


def policy(
    *,
    queue_policy: QueuePolicy = QueuePolicy.REJECT_NEW,
) -> BrainIntegrationRuntimePolicy:
    return BrainIntegrationRuntimePolicy(
        "brain.production",
        1,
        RuntimeSchedulerPolicy("brain.scheduler", 1, 2),
        tuple(
            RuntimeLanePolicy(
                lane.value,
                4,
                queue_policy,
                1,
                1.0,
                LaneErrorPolicy.ISOLATE,
            )
            for lane in BrainIntegrationLane
        ),
        TEST_SHUTDOWN_POLICY,
    )


def envelope(
    *,
    trace_id: str = "trace-1",
    trigger_id: str = "trigger-1",
    priority: BrainWorkPriority = BrainWorkPriority.NORMAL,
    source_revision: int = 1,
    goal_revision: int | None = None,
    attention_revision: int | None = None,
) -> BrainWorkEnvelope:
    return BrainWorkEnvelope(
        trace_id,
        trigger_id,
        ("event-1",),
        source_revision,
        goal_revision,
        attention_revision,
        priority,
        NOW,
    )


def work(
    work_id: str,
    module: BrainIntegrationModule,
    lane: BrainIntegrationLane,
    *,
    work_envelope: BrainWorkEnvelope | None = None,
    prerequisites: tuple[str, ...] = (),
    deadline_at: datetime | None = None,
) -> BrainIntegrationWork:
    return BrainIntegrationWork(
        work_id,
        module,
        lane,
        work_envelope or envelope(),
        {"work_id": work_id},
        prerequisites,
        deadline_at=deadline_at,
    )


def test_policy_requires_exact_lane_coverage_and_rejects_semantic_coalesce() -> None:
    scheduler = RuntimeSchedulerPolicy("brain.scheduler", 1, 2)
    lanes = policy().lane_policies
    with pytest.raises(ValueError, match="全lane"):
        BrainIntegrationRuntimePolicy("brain", 1, scheduler, lanes[:-1])
    with pytest.raises(ValueError, match="COALESCE"):
        policy(queue_policy=QueuePolicy.COALESCE)


def test_slow_background_work_does_not_block_direct_user_foreground_work() -> None:
    async def scenario() -> None:
        gate = asyncio.Event()
        runtime = BrainIntegrationRuntime(FakeRuntimeClock(NOW), policy())
        runtime.register_module(
            BrainIntegrationModule.REFLECTION,
            FakePort("reflection", gate=gate),
        )
        runtime.register_module(
            BrainIntegrationModule.INPUT_MEANING,
            FakePort("meaning"),
        )
        await runtime.start()

        assert runtime.submit(
            work(
                "reflection",
                BrainIntegrationModule.REFLECTION,
                BrainIntegrationLane.BACKGROUND_REFLECTION,
            )
        ).accepted
        assert runtime.submit(
            work(
                "input",
                BrainIntegrationModule.INPUT_MEANING,
                BrainIntegrationLane.FOREGROUND_INTERACTION,
                work_envelope=envelope(priority=BrainWorkPriority.DIRECT_USER),
            )
        ).accepted

        first = await runtime.next_outcome()
        assert first.work_id == "input"
        assert first.status is BrainWorkStatus.COMPLETED

        gate.set()
        second = await runtime.next_outcome()
        assert second.work_id == "reflection"
        assert second.status is BrainWorkStatus.COMPLETED
        await runtime.stop()

    asyncio.run(scenario())


def test_goal_prerequisite_blocks_only_dependent_planner() -> None:
    async def scenario() -> None:
        goal_gate = asyncio.Event()
        runtime = BrainIntegrationRuntime(FakeRuntimeClock(NOW), policy())
        runtime.register_module(
            BrainIntegrationModule.GOAL_COMMITMENT,
            FakePort("goal", gate=goal_gate),
        )
        runtime.register_module(BrainIntegrationModule.GOAL_PLANNING, FakePort("plan"))
        runtime.register_module(BrainIntegrationModule.SPEECH_SEMANTICS, FakePort("speech"))
        await runtime.start()

        goal = work(
            "goal",
            BrainIntegrationModule.GOAL_COMMITMENT,
            BrainIntegrationLane.COGNITIVE_NORMAL,
        )
        planner = work(
            "planner",
            BrainIntegrationModule.GOAL_PLANNING,
            BrainIntegrationLane.COGNITIVE_NORMAL,
            prerequisites=("goal",),
        )
        speech = work(
            "speech",
            BrainIntegrationModule.SPEECH_SEMANTICS,
            BrainIntegrationLane.SPEECH_PREPARATION,
        )
        assert runtime.submit(goal).accepted
        blocked = runtime.submit(planner)
        assert blocked.status is BrainWorkAdmissionStatus.PREREQUISITE_PENDING
        assert blocked.blocked_by == ("goal",)
        assert runtime.submit(speech).accepted

        assert (await runtime.next_outcome()).work_id == "speech"
        goal_gate.set()
        goal_outcome = await runtime.next_outcome()
        assert goal_outcome.work_id == "goal"
        assert goal_outcome.status is BrainWorkStatus.COMPLETED

        assert runtime.submit(planner).accepted
        planner_outcome = await runtime.next_outcome()
        assert planner_outcome.work_id == "planner"
        assert planner_outcome.status is BrainWorkStatus.COMPLETED
        await runtime.stop()

    asyncio.run(scenario())


def test_owner_freshness_rejection_never_executes_owner_work() -> None:
    async def scenario() -> None:
        port = FakePort("must-not-run", fresh=False)
        runtime = BrainIntegrationRuntime(FakeRuntimeClock(NOW), policy())
        runtime.register_module(BrainIntegrationModule.APPRAISAL, port)
        await runtime.start()

        assert runtime.submit(
            work(
                "stale",
                BrainIntegrationModule.APPRAISAL,
                BrainIntegrationLane.COGNITIVE_NORMAL,
            )
        ).accepted
        outcome = await runtime.next_outcome()
        assert outcome.status is BrainWorkStatus.STALE
        assert port.calls == []
        assert runtime.trace("trace-1").intervals[0].status is BrainWorkStatus.STALE
        await runtime.stop()

    asyncio.run(scenario())


def test_supersede_preserves_public_superseded_truth() -> None:
    async def scenario() -> None:
        gate = asyncio.Event()
        started = asyncio.Event()
        runtime = BrainIntegrationRuntime(FakeRuntimeClock(NOW), policy())
        runtime.register_module(
            BrainIntegrationModule.EXECUTIVE,
            FakePort("decision", gate=gate, started=started),
        )
        await runtime.start()

        assert runtime.submit(
            work(
                "decision",
                BrainIntegrationModule.EXECUTIVE,
                BrainIntegrationLane.FOREGROUND_INTERACTION,
            )
        ).accepted
        await started.wait()
        assert runtime.supersede("decision", "newer attention claim")
        outcome = await runtime.next_outcome()
        assert outcome.status is BrainWorkStatus.SUPERSEDED
        assert runtime.trace("trace-1").intervals[0].status is BrainWorkStatus.SUPERSEDED
        gate.set()
        await runtime.stop()

    asyncio.run(scenario())


def test_deadline_and_unregistered_module_are_trace_visible() -> None:
    async def scenario() -> None:
        clock = FakeRuntimeClock(NOW)
        runtime = BrainIntegrationRuntime(clock, policy())
        runtime.register_module(BrainIntegrationModule.INPUT_MEANING, FakePort("meaning"))
        await runtime.start()

        rejected = runtime.submit(
            work(
                "unregistered",
                BrainIntegrationModule.MEMORY,
                BrainIntegrationLane.COGNITIVE_NORMAL,
            )
        )
        assert rejected.status is BrainWorkAdmissionStatus.REJECTED
        assert (await runtime.next_outcome()).status is BrainWorkStatus.REJECTED

        expiring = work(
            "deadline",
            BrainIntegrationModule.INPUT_MEANING,
            BrainIntegrationLane.FOREGROUND_INTERACTION,
            work_envelope=envelope(trace_id="trace-2", trigger_id="trigger-2"),
            deadline_at=NOW + timedelta(seconds=1),
        )
        assert runtime.submit(expiring).accepted
        clock.advance(1)
        outcome = await runtime.next_outcome()
        assert outcome.status is BrainWorkStatus.TIMED_OUT
        assert runtime.trace("trace-2").intervals[0].status is BrainWorkStatus.TIMED_OUT
        await runtime.stop()

    asyncio.run(scenario())


def test_trace_records_only_owner_confirmed_evidence_and_finalizes_after_terminal_work() -> None:
    async def scenario() -> None:
        gate = asyncio.Event()
        runtime = BrainIntegrationRuntime(FakeRuntimeClock(NOW), policy())
        runtime.register_module(
            BrainIntegrationModule.EXECUTIVE,
            FakePort("decision", gate=gate),
        )
        await runtime.start()
        assert runtime.submit(
            work(
                "decision-work",
                BrainIntegrationModule.EXECUTIVE,
                BrainIntegrationLane.FOREGROUND_INTERACTION,
            )
        ).accepted

        with pytest.raises(ValueError, match="未終了"):
            runtime.finalize_trace(
                "trace-1",
                BrainIntegrationTerminalOutcome.COMPLETED,
            )

        gate.set()
        assert (await runtime.next_outcome()).status is BrainWorkStatus.COMPLETED
        runtime.record_revision_event(
            "trace-1",
            BrainRevisionEvent(
                "revision-1",
                BrainIntegrationModule.GOAL_COMMITMENT,
                2,
                NOW,
            ),
        )
        runtime.record_decision_id("trace-1", "decision-1")
        runtime.record_goal_transition_id("trace-1", "goal-transition-1")
        runtime.record_activity_id("trace-1", "activity-1")
        runtime.record_speech_candidate_id("trace-1", "speech-1")

        trace = runtime.finalize_trace(
            "trace-1",
            BrainIntegrationTerminalOutcome.COMPLETED,
        )
        assert trace.terminal_outcome is BrainIntegrationTerminalOutcome.COMPLETED
        assert trace.decision_ids == ("decision-1",)
        assert trace.goal_transition_ids == ("goal-transition-1",)
        assert trace.activity_ids == ("activity-1",)
        assert trace.speech_candidate_ids == ("speech-1",)
        assert trace.revision_events[0].revision == 2
        await runtime.stop()

    asyncio.run(scenario())
