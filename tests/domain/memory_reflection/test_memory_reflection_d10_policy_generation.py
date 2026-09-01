from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from app.domain.memory_reflection import (
    MemoryCandidateProposal,
    ReflectionAcceptancePolicy,
    ReflectionCandidateAuthority,
    ReflectionContextSnapshot,
    ReflectionCoordinator,
    ReflectionSupportObservation,
)
from tests.domain.memory_reflection.policy_fixtures import reflection_operational_policy


class ZeroProposalPort:
    async def propose(
        self, _: ReflectionContextSnapshot
    ) -> tuple[MemoryCandidateProposal, ...]:
        return ()


class UnusedSupportPort:
    async def observe(
        self,
        _: ReflectionContextSnapshot,
        candidate: MemoryCandidateProposal,
    ) -> ReflectionSupportObservation:
        raise AssertionError(candidate.proposal_id)


def authority() -> ReflectionCandidateAuthority:
    return ReflectionCandidateAuthority(ReflectionAcceptancePolicy("acceptance:d10", 1))


def test_same_policy_generation_cannot_change_numeric_contract() -> None:
    async def run() -> None:
        initial = reflection_operational_policy(
            revision=1,
            max_primary_sources=1,
        )
        coordinator = ReflectionCoordinator(
            ZeroProposalPort(),
            UnusedSupportPort(),
            authority(),
            operational_policy=initial,
            max_pending_tasks=8,
        )
        changed_same_generation = replace(initial, max_primary_sources=2)

        with pytest.raises(
            ValueError,
            match="同一Reflection operational policy generation",
        ):
            await coordinator.update_operational_policy(changed_same_generation)

        assert coordinator.operational_policy == initial
        await coordinator.update_operational_policy(initial)
        assert coordinator.operational_policy == initial

    asyncio.run(run())
