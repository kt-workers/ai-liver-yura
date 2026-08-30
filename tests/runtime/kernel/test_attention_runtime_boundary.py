import asyncio
from datetime import datetime, timezone

from app.domain.attention import (
    AttentionCoordinator,
    AttentionIngressOperation,
    AttentionIngressSignal,
    AttentionPriority,
    AttentionSourceKind,
    AttentionTurnStore,
    ExecutiveTriggerEligibility,
)
from app.domain.contracts import RevisionVector
from app.runtime.kernel import (
    FakeRuntimeClock,
    LaneErrorPolicy,
    QueuePolicy,
    RuntimeCoordinator as KernelRuntimeCoordinator,
    RuntimeLanePolicy as KernelRuntimeLanePolicy,
    RuntimeSchedulerPolicy,
    RuntimeWorkItem,
    WorkDisposition,
    WorkPriority,
)

NOW = datetime(2026, 8, 16, tzinfo=timezone.utc)
TEST_SCHEDULER_POLICY = RuntimeSchedulerPolicy("test.scheduler", 1, 8)


def RuntimeCoordinator(clock: FakeRuntimeClock) -> KernelRuntimeCoordinator:
    return KernelRuntimeCoordinator(clock, TEST_SCHEDULER_POLICY)


def RuntimeLanePolicy(
    lane_id: str,
    queue_capacity: int,
    queue_policy: QueuePolicy,
) -> KernelRuntimeLanePolicy:
    return KernelRuntimeLanePolicy(
        lane_id,
        queue_capacity,
        queue_policy,
        1,
        1.0,
        LaneErrorPolicy.ISOLATE,
    )


def _work(work_id: str, lane: str, payload: object) -> RuntimeWorkItem[object]:
    return RuntimeWorkItem(
        work_id,
        lane,
        payload,
        WorkPriority.NORMAL,
        RevisionVector(1),
        NOW,
    )


def test_slow_preparation_and_presentation_do_not_block_attention_claim() -> None:
    async def scenario() -> None:
        gate = asyncio.Event()
        executive_triggers: list[str] = []
        runtime = RuntimeCoordinator(FakeRuntimeClock(NOW))
        store = AttentionTurnStore()

        def enqueue(trigger: ExecutiveTriggerEligibility) -> None:
            runtime.submit(_work(f"executive-{len(executive_triggers)}", "executive", trigger))

        application = AttentionCoordinator(store, store, enqueue)

        async def blocked_handler(work: RuntimeWorkItem[object], _token: object) -> object:
            await gate.wait()
            return work.payload

        async def attention_handler(work: RuntimeWorkItem[object], _token: object) -> object:
            if not isinstance(work.payload, AttentionIngressSignal):
                raise ValueError("attention laneはAttentionIngressSignalだけを受理します")
            return application.handle(work.payload, 1, NOW)

        async def executive_handler(work: RuntimeWorkItem[object], _token: object) -> object:
            trigger = work.payload
            if not isinstance(trigger, ExecutiveTriggerEligibility):
                raise ValueError("executive laneはExecutiveTriggerEligibilityだけを受理します")
            executive_triggers.append(trigger.source_ref)
            return trigger

        runtime.register_lane(
            RuntimeLanePolicy("preparation", 2, QueuePolicy.REJECT_NEW), blocked_handler
        )
        runtime.register_lane(
            RuntimeLanePolicy("presentation", 2, QueuePolicy.REJECT_NEW), blocked_handler
        )
        runtime.register_lane(
            RuntimeLanePolicy("attention", 4, QueuePolicy.REJECT_NEW), attention_handler
        )
        runtime.register_lane(
            RuntimeLanePolicy("executive", 4, QueuePolicy.REJECT_NEW), executive_handler
        )
        await runtime.start()
        runtime.submit(_work("slow-preparation", "preparation", "slow"))
        runtime.submit(_work("speech-a", "presentation", "presenting"))
        runtime.submit(
            _work(
                "user-input",
                "attention",
                AttentionIngressSignal(
                    "user-signal",
                    AttentionIngressOperation.OFFER,
                    "user-1",
                    AttentionSourceKind.USER_INTERACTION,
                    1,
                    NOW,
                    trusted_direct_user=True,
                ),
            )
        )
        attention_outcome = await runtime.next_outcome()
        executive_outcome = await runtime.next_outcome()
        assert {attention_outcome.work_id, executive_outcome.work_id} == {
            "user-input",
            "executive-0",
        }
        assert attention_outcome.disposition is WorkDisposition.COMPLETED
        assert executive_outcome.disposition is WorkDisposition.COMPLETED
        assert executive_triggers == ["user-1"]
        store.resolve(
            AttentionIngressSignal(
                "user-resolved",
                AttentionIngressOperation.RESOLVE,
                "user-1",
                AttentionSourceKind.USER_INTERACTION,
                2,
                NOW,
            )
        )
        runtime.submit(
            _work(
                "appraisal",
                "attention",
                AttentionIngressSignal(
                    "appraisal-signal",
                    AttentionIngressOperation.OFFER,
                    "appraisal-1",
                    AttentionSourceKind.APPRAISAL,
                    3,
                    NOW,
                    requested_priority=AttentionPriority.NORMAL,
                ),
            )
        )
        assert (await runtime.next_outcome()).work_id == "appraisal"
        assert (await runtime.next_outcome()).work_id == "executive-1"
        assert executive_triggers == ["user-1", "appraisal-1"]
        gate.set()
        await runtime.next_outcome()
        await runtime.next_outcome()
        await runtime.stop()

    asyncio.run(scenario())
