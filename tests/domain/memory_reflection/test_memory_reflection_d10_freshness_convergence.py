from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.domain.memory.contracts import (
    MemoryContent,
    MemoryFreshnessState,
    MemoryKind,
    MemoryTemporalState,
)
from app.domain.memory_reflection import (
    MemoryCandidateProposal,
    ReflectionAcceptancePolicy,
    ReflectionCandidateAuthority,
    ReflectionCandidateStatus,
    ReflectionContextSnapshot,
    ReflectionCoordinator,
    ReflectionOperationalPolicy,
    ReflectionSourceEvidence,
    ReflectionSourceKind,
    ReflectionSupportObservation,
    ReflectionSupportRelation,
    ReflectionTrigger,
    ReflectionTriggerKind,
)
from app.domain.memory_reflection.contracts import ReflectionPersistenceHint
from tests.domain.memory_reflection.policy_fixtures import reflection_operational_policy

NOW = datetime(2026, 9, 1, 11, 0, tzinfo=timezone.utc)


def source(source_ref: str) -> ReflectionSourceEvidence:
    return ReflectionSourceEvidence(
        source_ref,
        ReflectionSourceKind.PRESENTATION_FACT,
        "trusted_owner",
        1,
        NOW,
        {"summary": source_ref},
        (f"provenance:{source_ref}",),
        0.8,
    )


def context(
    policy: ReflectionOperationalPolicy,
    reflection_id: str,
    *sources: ReflectionSourceEvidence,
) -> ReflectionContextSnapshot:
    ordered = tuple(sorted(sources, key=lambda item: item.source_ref))
    trigger = ReflectionTrigger(
        f"trigger:{reflection_id}",
        ReflectionTriggerKind.EPISODE_COMPLETED,
        tuple(item.source_ref for item in ordered),
        1,
        10,
        True,
        NOW,
    )
    return ReflectionContextSnapshot(
        reflection_id,
        trigger,
        ordered,
        (),
        1,
        1,
        NOW,
        f"trace:{reflection_id}",
        policy.policy_id,
        policy.policy_revision,
    )


def proposal(source_ref: str) -> MemoryCandidateProposal:
    return MemoryCandidateProposal(
        "proposal:1",
        MemoryKind.EPISODIC,
        MemoryContent("episode", {"value": "remember"}),
        (source_ref,),
        0.8,
        0.7,
        ReflectionPersistenceHint.DURABLE,
        0.6,
        MemoryTemporalState(MemoryFreshnessState.HISTORICAL),
    )


def authority() -> ReflectionCandidateAuthority:
    return ReflectionCandidateAuthority(ReflectionAcceptancePolicy("acceptance:d10", 1))


class CountingSupportPort:
    def __init__(self) -> None:
        self.calls = 0

    async def observe(
        self,
        _: ReflectionContextSnapshot,
        candidate: MemoryCandidateProposal,
    ) -> ReflectionSupportObservation:
        self.calls += 1
        return ReflectionSupportObservation(
            candidate.proposal_id,
            ReflectionSupportRelation.SUPPORTED,
            candidate.source_refs,
            (),
            (),
            0.8,
        )


def test_live_context_bound_violation_converges_to_rejected_policy() -> None:
    class ProposalPort:
        async def propose(
            self, _: ReflectionContextSnapshot
        ) -> tuple[MemoryCandidateProposal, ...]:
            return (proposal("source:1"),)

    async def run() -> None:
        policy = reflection_operational_policy(max_primary_sources=1)
        captured = context(policy, "reflection:captured", source("source:1"))
        live = context(
            policy,
            "reflection:captured",
            source("source:1"),
            source("source:2"),
        )
        support_port = CountingSupportPort()
        coordinator = ReflectionCoordinator(
            ProposalPort(),
            support_port,
            authority(),
            operational_policy=policy,
            max_pending_tasks=8,
            live_context=lambda _: live,
        )

        result = await coordinator.submit(captured)

        assert result.results[0].status is ReflectionCandidateStatus.REJECTED_POLICY
        assert result.results[0].candidate is None
        assert support_port.calls == 0

    asyncio.run(run())


def test_policy_change_while_waiting_for_concurrency_skips_old_provider_call() -> None:
    class BlockingProposalPort:
        def __init__(self) -> None:
            self.calls = 0
            self.first_started = asyncio.Event()
            self.release = asyncio.Event()

        async def propose(
            self, _: ReflectionContextSnapshot
        ) -> tuple[MemoryCandidateProposal, ...]:
            self.calls += 1
            if self.calls > 1:
                raise AssertionError("stale request must not call provider")
            self.first_started.set()
            await self.release.wait()
            return ()

    async def run() -> None:
        policy_v1 = reflection_operational_policy(
            revision=1,
            max_concurrent_reflections=1,
        )
        provider = BlockingProposalPort()
        coordinator = ReflectionCoordinator(
            provider,
            CountingSupportPort(),
            authority(),
            operational_policy=policy_v1,
            max_pending_tasks=8,
        )
        first = coordinator.submit(
            context(policy_v1, "reflection:first", source("source:1"))
        )
        await provider.first_started.wait()
        second = coordinator.submit(
            context(policy_v1, "reflection:second", source("source:2"))
        )

        await coordinator.update_operational_policy(
            reflection_operational_policy(
                revision=2,
                max_concurrent_reflections=1,
            )
        )
        provider.release.set()
        first_result, second_result = await asyncio.gather(first, second)

        assert first_result.results[0].status is ReflectionCandidateStatus.REJECTED_STALE
        assert second_result.results[0].status is ReflectionCandidateStatus.REJECTED_STALE
        assert provider.calls == 1

    asyncio.run(run())
