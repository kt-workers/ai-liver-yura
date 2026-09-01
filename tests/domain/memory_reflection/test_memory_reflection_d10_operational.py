from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Callable, cast

import pytest

from app.domain.memory.contracts import (
    MemoryContent,
    MemoryFreshnessState,
    MemoryKind,
    MemoryRelationKind,
    MemoryTemporalState,
)
from app.domain.memory_reflection import (
    MemoryCandidateProposal,
    ReflectionAcceptancePolicy,
    ReflectionCandidateAuthority,
    ReflectionCandidateStatus,
    ReflectionContextSnapshot,
    ReflectionCoordinator,
    ReflectionOperationalError,
    ReflectionOperationalFailureCode,
    ReflectionOperationalPolicy,
    ReflectionRelationHint,
    ReflectionSourceEvidence,
    ReflectionSourceKind,
    ReflectionSupportObservation,
    ReflectionSupportRelation,
    ReflectionTrigger,
    ReflectionTriggerKind,
    bound_source_excerpt,
    reflection_source_order_key,
    validate_reflection_context_bounds,
    validate_reflection_proposals_bounds,
    validate_reflection_support_bounds,
)
from app.domain.memory_reflection.contracts import (
    ReflectionPersistenceHint,
    ReflectionRelatedMemory,
)
from tests.domain.memory_reflection.policy_fixtures import reflection_operational_policy

NOW = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)


def source(
    source_ref: str,
    kind: ReflectionSourceKind = ReflectionSourceKind.PRESENTATION_FACT,
    *,
    occurred_at: datetime = NOW,
    excerpt: str | None = None,
    excerpt_truncated: bool = False,
) -> ReflectionSourceEvidence:
    return ReflectionSourceEvidence(
        source_ref,
        kind,
        "trusted_owner",
        1,
        occurred_at,
        {"summary": source_ref},
        (f"provenance:{source_ref}",),
        0.8,
        False,
        excerpt,
        excerpt_truncated,
    )


def context_for(
    policy: ReflectionOperationalPolicy,
    *sources: ReflectionSourceEvidence,
    related_count: int = 0,
    sort_sources: bool = True,
    reflection_id: str = "reflection:d10",
) -> ReflectionContextSnapshot:
    selected = (
        tuple(sorted(sources, key=reflection_source_order_key))
        if sort_sources
        else tuple(sources)
    )
    trigger = ReflectionTrigger(
        f"trigger:{reflection_id}",
        ReflectionTriggerKind.EPISODE_COMPLETED,
        tuple(item.source_ref for item in selected),
        1,
        10,
        True,
        NOW,
    )
    return ReflectionContextSnapshot(
        reflection_id,
        trigger,
        selected,
        tuple(
            ReflectionRelatedMemory(f"memory:{index}", 1)
            for index in range(related_count)
        ),
        1,
        1,
        NOW,
        f"trace:{reflection_id}",
        policy.policy_id,
        policy.policy_revision,
    )


def proposal(
    proposal_id: str,
    source_ref: str = "source:1",
    *,
    relation_hints: tuple[ReflectionRelationHint, ...] = (),
    rationale_refs: tuple[str, ...] = (),
) -> MemoryCandidateProposal:
    return MemoryCandidateProposal(
        proposal_id,
        MemoryKind.EPISODIC,
        MemoryContent("episode", {"value": proposal_id}),
        (source_ref,),
        0.8,
        0.7,
        ReflectionPersistenceHint.DURABLE,
        0.6,
        MemoryTemporalState(MemoryFreshnessState.HISTORICAL),
        tuple(hint.related_memory_id for hint in relation_hints),
        relation_hints,
        rationale_refs,
    )


def authority() -> ReflectionCandidateAuthority:
    return ReflectionCandidateAuthority(ReflectionAcceptancePolicy("acceptance:d10", 1))


@pytest.mark.parametrize(
    "factory",
    (
        lambda: reflection_operational_policy(max_primary_sources=cast(int, True)),
        lambda: reflection_operational_policy(max_related_memory_items=cast(int, True)),
        lambda: reflection_operational_policy(max_context_estimated_tokens=cast(int, True)),
        lambda: reflection_operational_policy(max_source_excerpt_codepoints=cast(int, True)),
        lambda: reflection_operational_policy(max_proposals_per_reflection=cast(int, True)),
        lambda: reflection_operational_policy(
            max_relation_hints_per_proposal=cast(int, True)
        ),
        lambda: reflection_operational_policy(max_evidence_refs_per_proposal=cast(int, True)),
        lambda: reflection_operational_policy(max_concurrent_reflections=cast(int, True)),
    ),
)
def test_operational_policy_rejects_bool_for_every_numeric_field(
    factory: Callable[[], ReflectionOperationalPolicy],
) -> None:
    with pytest.raises(ValueError):
        factory()


def test_primary_source_bound_accepts_below_and_equal_but_rejects_above() -> None:
    policy = reflection_operational_policy(max_primary_sources=2)
    one = context_for(policy, source("source:1"))
    two = context_for(policy, source("source:1"), source("source:2"))
    three = context_for(
        policy,
        source("source:1"),
        source("source:2"),
        source("source:3"),
    )

    validate_reflection_context_bounds(one, policy)
    validate_reflection_context_bounds(two, policy)
    with pytest.raises(ReflectionOperationalError) as exc_info:
        validate_reflection_context_bounds(three, policy)
    assert exc_info.value.code is ReflectionOperationalFailureCode.CONTEXT_TOO_LARGE


def test_related_memory_bound_accepts_zero_and_equal_but_rejects_above() -> None:
    policy = reflection_operational_policy(max_related_memory_items=1)
    zero = context_for(policy, source("source:1"), related_count=0)
    one = context_for(policy, source("source:1"), related_count=1)
    two = context_for(policy, source("source:1"), related_count=2)

    validate_reflection_context_bounds(zero, policy)
    validate_reflection_context_bounds(one, policy)
    with pytest.raises(ReflectionOperationalError):
        validate_reflection_context_bounds(two, policy)


def test_context_token_budget_accepts_equal_and_rejects_one_less() -> None:
    roomy = reflection_operational_policy(max_context_estimated_tokens=100_000)
    snapshot = context_for(roomy, source("source:1"))
    exact = replace(roomy, max_context_estimated_tokens=snapshot.estimated_tokens)
    too_small = replace(
        roomy,
        max_context_estimated_tokens=snapshot.estimated_tokens - 1,
    )

    assert validate_reflection_context_bounds(snapshot, exact) == snapshot.estimated_tokens
    with pytest.raises(ReflectionOperationalError) as exc_info:
        validate_reflection_context_bounds(snapshot, too_small)
    assert exc_info.value.code is ReflectionOperationalFailureCode.CONTEXT_TOO_LARGE


def test_primary_sources_require_canonical_order() -> None:
    policy = reflection_operational_policy()
    later_kind = source("source:z", ReflectionSourceKind.PRESENTATION_FACT)
    earlier_kind = source("source:a", ReflectionSourceKind.INPUT_MEANING)
    snapshot = context_for(
        policy,
        later_kind,
        earlier_kind,
        sort_sources=False,
    )

    with pytest.raises(ReflectionOperationalError) as exc_info:
        validate_reflection_context_bounds(snapshot, policy)
    assert exc_info.value.code is ReflectionOperationalFailureCode.CONTEXT_ORDER_INVALID


def test_source_order_is_time_then_kind_then_unicode_source_ref() -> None:
    early = source(
        "source:z",
        ReflectionSourceKind.PRESENTATION_FACT,
        occurred_at=NOW - timedelta(seconds=1),
    )
    same_time_later_kind = source("source:a", ReflectionSourceKind.PRESENTATION_FACT)
    same_time_earlier_kind = source("source:z", ReflectionSourceKind.INPUT_MEANING)
    same_kind_smaller_id = source("source:0", ReflectionSourceKind.PRESENTATION_FACT)

    assert [
        item.source_ref
        for item in sorted(
            (same_time_later_kind, same_time_earlier_kind, early, same_kind_smaller_id),
            key=reflection_source_order_key,
        )
    ] == ["source:z", "source:z", "source:0", "source:a"]


def test_source_excerpt_uses_unicode_codepoints_and_preserves_truncation_metadata() -> None:
    policy = reflection_operational_policy(max_source_excerpt_codepoints=2)
    bounded, truncated = bound_source_excerpt("ゆら海", policy)
    assert bounded == "ゆら"
    assert truncated

    snapshot = context_for(
        policy,
        source("source:1", excerpt=bounded, excerpt_truncated=truncated),
    )
    validate_reflection_context_bounds(snapshot, policy)

    oversized = context_for(policy, source("source:1", excerpt="ゆら海"))
    with pytest.raises(ReflectionOperationalError):
        validate_reflection_context_bounds(oversized, policy)


def test_proposal_count_overflow_rejects_whole_result_without_first_n_support_calls() -> None:
    class ProposalPort:
        async def propose(
            self, _: ReflectionContextSnapshot
        ) -> tuple[MemoryCandidateProposal, ...]:
            return (
                proposal("proposal:1"),
                proposal("proposal:2"),
                proposal("proposal:3"),
            )

    class CountingSupportPort:
        def __init__(self) -> None:
            self.calls = 0

        async def observe(
            self,
            _: ReflectionContextSnapshot,
            item: MemoryCandidateProposal,
        ) -> ReflectionSupportObservation:
            self.calls += 1
            return ReflectionSupportObservation(
                item.proposal_id,
                ReflectionSupportRelation.SUPPORTED,
                item.source_refs,
                (),
                (),
                0.8,
            )

    async def run() -> None:
        policy = reflection_operational_policy(max_proposals_per_reflection=2)
        snapshot = context_for(policy, source("source:1"))
        support_port = CountingSupportPort()
        coordinator = ReflectionCoordinator(
            ProposalPort(),
            support_port,
            authority(),
            operational_policy=policy,
            max_pending_tasks=8,
        )

        result = await coordinator.submit(snapshot)

        assert len(result.results) == 1
        assert result.results[0].status is ReflectionCandidateStatus.REJECTED_POLICY
        assert support_port.calls == 0

    asyncio.run(run())


def test_relation_hint_and_proposal_evidence_bounds_are_fail_closed() -> None:
    policy = reflection_operational_policy(
        max_relation_hints_per_proposal=1,
        max_evidence_refs_per_proposal=2,
    )
    first = ReflectionRelationHint(
        "memory:1",
        1,
        MemoryRelationKind.REFINES,
        ("evidence:1",),
        0.8,
    )
    second = ReflectionRelationHint(
        "memory:2",
        1,
        MemoryRelationKind.SUPPORTS,
        ("evidence:2",),
        0.8,
    )
    validate_reflection_proposals_bounds(
        (proposal("proposal:ok", relation_hints=(first,), rationale_refs=("evidence:2",)),),
        policy,
    )
    with pytest.raises(ReflectionOperationalError):
        validate_reflection_proposals_bounds(
            (proposal("proposal:hints", relation_hints=(first, second)),),
            policy,
        )
    with pytest.raises(ReflectionOperationalError):
        validate_reflection_proposals_bounds(
            (
                proposal(
                    "proposal:evidence",
                    relation_hints=(first,),
                    rationale_refs=("evidence:2", "evidence:3"),
                ),
            ),
            policy,
        )


def test_support_evidence_bound_accepts_equal_and_rejects_above() -> None:
    policy = reflection_operational_policy(max_evidence_refs_per_proposal=2)
    exact = ReflectionSupportObservation(
        "proposal:1",
        ReflectionSupportRelation.SUPPORTED,
        ("source:1", "source:2"),
        (),
        (),
        0.8,
    )
    overflow = ReflectionSupportObservation(
        "proposal:1",
        ReflectionSupportRelation.SUPPORTED,
        ("source:1", "source:2", "source:3"),
        (),
        (),
        0.8,
    )
    validate_reflection_support_bounds(exact, policy)
    with pytest.raises(ReflectionOperationalError) as exc_info:
        validate_reflection_support_bounds(overflow, policy)
    assert exc_info.value.code is ReflectionOperationalFailureCode.SUPPORT_RESULT_TOO_LARGE


def test_effective_concurrency_is_minimum_of_reflection_and_lane_policy() -> None:
    class BlockingProposalPort:
        def __init__(self) -> None:
            self.calls = 0
            self.two_started = asyncio.Event()
            self.release = asyncio.Event()

        async def propose(
            self, _: ReflectionContextSnapshot
        ) -> tuple[MemoryCandidateProposal, ...]:
            self.calls += 1
            if self.calls == 2:
                self.two_started.set()
            await self.release.wait()
            return ()

    class SupportPort:
        async def observe(
            self,
            _: ReflectionContextSnapshot,
            item: MemoryCandidateProposal,
        ) -> ReflectionSupportObservation:
            raise AssertionError(f"zero proposals expected: {item.proposal_id}")

    async def run() -> None:
        policy = reflection_operational_policy(max_concurrent_reflections=3)
        provider = BlockingProposalPort()
        coordinator = ReflectionCoordinator(
            provider,
            SupportPort(),
            authority(),
            operational_policy=policy,
            lane_max_concurrency=2,
            max_pending_tasks=8,
        )
        tasks = tuple(
            coordinator.submit(
                context_for(
                    policy,
                    source(f"source:{index}"),
                    reflection_id=f"reflection:{index}",
                )
            )
            for index in range(3)
        )

        await asyncio.wait_for(provider.two_started.wait(), timeout=1.0)
        await asyncio.sleep(0)
        assert coordinator.effective_max_concurrency == 2
        assert coordinator.active_reflection_count == 2
        assert provider.calls == 2
        provider.release.set()
        await asyncio.gather(*tasks)
        assert provider.calls == 3
        assert coordinator.active_reflection_count == 0

    asyncio.run(run())


def test_policy_revision_change_during_proposal_await_stales_without_support() -> None:
    class BlockingProposalPort:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def propose(
            self, _: ReflectionContextSnapshot
        ) -> tuple[MemoryCandidateProposal, ...]:
            self.started.set()
            await self.release.wait()
            return (proposal("proposal:1"),)

    class CountingSupportPort:
        def __init__(self) -> None:
            self.calls = 0

        async def observe(
            self,
            _: ReflectionContextSnapshot,
            item: MemoryCandidateProposal,
        ) -> ReflectionSupportObservation:
            self.calls += 1
            return ReflectionSupportObservation(
                item.proposal_id,
                ReflectionSupportRelation.SUPPORTED,
                item.source_refs,
                (),
                (),
                0.8,
            )

    async def run() -> None:
        policy = reflection_operational_policy(revision=1)
        proposal_port = BlockingProposalPort()
        support_port = CountingSupportPort()
        coordinator = ReflectionCoordinator(
            proposal_port,
            support_port,
            authority(),
            operational_policy=policy,
            max_pending_tasks=8,
        )
        task = coordinator.submit(context_for(policy, source("source:1")))
        await proposal_port.started.wait()
        await coordinator.update_operational_policy(
            reflection_operational_policy(revision=2)
        )
        proposal_port.release.set()
        result = await task

        assert result.results[0].status is ReflectionCandidateStatus.REJECTED_STALE
        assert support_port.calls == 0

    asyncio.run(run())


def test_policy_revision_change_during_support_await_stales_before_acceptance() -> None:
    class ProposalPort:
        async def propose(
            self, _: ReflectionContextSnapshot
        ) -> tuple[MemoryCandidateProposal, ...]:
            return (proposal("proposal:1"),)

    class BlockingSupportPort:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def observe(
            self,
            _: ReflectionContextSnapshot,
            item: MemoryCandidateProposal,
        ) -> ReflectionSupportObservation:
            self.started.set()
            await self.release.wait()
            return ReflectionSupportObservation(
                item.proposal_id,
                ReflectionSupportRelation.SUPPORTED,
                item.source_refs,
                (),
                (),
                0.8,
            )

    async def run() -> None:
        policy = reflection_operational_policy(revision=1)
        support_port = BlockingSupportPort()
        coordinator = ReflectionCoordinator(
            ProposalPort(),
            support_port,
            authority(),
            operational_policy=policy,
            max_pending_tasks=8,
        )
        task = coordinator.submit(context_for(policy, source("source:1")))
        await support_port.started.wait()
        await coordinator.update_operational_policy(
            reflection_operational_policy(revision=2)
        )
        support_port.release.set()
        result = await task

        assert result.results[0].status is ReflectionCandidateStatus.REJECTED_STALE
        assert result.results[0].candidate is None

    asyncio.run(run())


def test_production_coordinator_has_no_hidden_operational_or_queue_default() -> None:
    class ProposalPort:
        async def propose(
            self, _: ReflectionContextSnapshot
        ) -> tuple[MemoryCandidateProposal, ...]:
            return ()

    class SupportPort:
        async def observe(
            self,
            _: ReflectionContextSnapshot,
            item: MemoryCandidateProposal,
        ) -> ReflectionSupportObservation:
            raise AssertionError(item.proposal_id)

    constructor = cast(
        Callable[
            [ProposalPort, SupportPort, ReflectionCandidateAuthority],
            ReflectionCoordinator,
        ],
        ReflectionCoordinator,
    )
    with pytest.raises(TypeError):
        constructor(ProposalPort(), SupportPort(), authority())
