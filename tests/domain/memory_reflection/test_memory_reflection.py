from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
    ReflectionRelationHint,
    ReflectionSourceEvidence,
    ReflectionSourceKind,
    ReflectionSupportObservation,
    ReflectionSupportRelation,
    ReflectionTrigger,
    ReflectionTriggerKind,
)
from app.domain.memory_reflection.contracts import (
    ReflectionEventKind,
    ReflectionPersistenceHint,
    ReflectionRelatedMemory,
)

NOW = datetime(2026, 8, 25, tzinfo=timezone.utc)


def source(
    source_ref: str,
    kind: ReflectionSourceKind,
    *,
    retracted: bool = False,
    revision: int = 1,
) -> ReflectionSourceEvidence:
    return ReflectionSourceEvidence(
        source_ref,
        kind,
        "trusted_owner",
        revision,
        NOW,
        {"summary": "bounded"},
        (f"provenance:{source_ref}",),
        0.8,
        retracted,
    )


def context(*sources: ReflectionSourceEvidence) -> ReflectionContextSnapshot:
    trigger = ReflectionTrigger(
        "trigger-1",
        ReflectionTriggerKind.EPISODE_COMPLETED,
        tuple(item.source_ref for item in sources),
        4,
        10,
        True,
        NOW,
    )
    return ReflectionContextSnapshot(
        "reflection-1",
        trigger,
        sources,
        (ReflectionRelatedMemory("memory-1", 2),),
        4,
        8,
        NOW,
        "trace-1",
    )


def proposal(
    *source_refs: str,
    predicate: str = "episode",
    kind: MemoryKind = MemoryKind.EPISODIC,
    deterministic_capture: bool = False,
    relation_hints: tuple[ReflectionRelationHint, ...] = (),
) -> MemoryCandidateProposal:
    return MemoryCandidateProposal(
        "proposal-1",
        kind,
        MemoryContent(predicate, {"value": "remember"}, "user-1"),
        source_refs,
        0.8,
        0.7,
        ReflectionPersistenceHint.DURABLE,
        0.6,
        MemoryTemporalState(freshness=MemoryFreshnessState.HISTORICAL),
        tuple(hint.related_memory_id for hint in relation_hints),
        relation_hints,
        ("rationale-only",),
        deterministic_capture,
    )


def support(
    *refs: str,
    relation: ReflectionSupportRelation = ReflectionSupportRelation.SUPPORTED,
) -> ReflectionSupportObservation:
    return ReflectionSupportObservation(
        "proposal-1",
        relation,
        refs,
        (),
        refs if relation is ReflectionSupportRelation.CONTRADICTED else (),
        0.75,
    )


def authority() -> ReflectionCandidateAuthority:
    return ReflectionCandidateAuthority(ReflectionAcceptancePolicy("reflection-v1", 1))


def test_prepared_or_planned_source_cannot_claim_actual_speech_or_execution() -> None:
    prepared = context(source("prepared-1", ReflectionSourceKind.INPUT_MEANING))
    speech = proposal("prepared-1", predicate="actual_speech")
    planned = context(source("plan-1", ReflectionSourceKind.ACTIVITY_RESULT))
    activity = proposal("plan-1", predicate="executed_activity")

    assert authority().accept(prepared, speech, support("prepared-1")).status is (
        ReflectionCandidateStatus.REJECTED_INVALID_PROVENANCE
    )
    assert authority().accept(planned, activity, support("plan-1")).status is (
        ReflectionCandidateStatus.REJECTED_INVALID_PROVENANCE
    )


def test_presented_speech_and_execution_fact_are_eligible() -> None:
    presented = context(source("presentation-1", ReflectionSourceKind.PRESENTATION_FACT))
    speech = proposal("presentation-1", predicate="actual_speech")
    executed = context(source("execution-1", ReflectionSourceKind.EXECUTION_FACT))
    activity = proposal("execution-1", predicate="executed_activity")

    speech_result = authority().accept(presented, speech, support("presentation-1"))
    activity_result = authority().accept(executed, activity, support("execution-1"))

    assert speech_result.candidate is not None and speech_result.candidate.claims_actual_speech
    assert activity_result.candidate is not None
    assert activity_result.candidate.claims_executed_activity


def test_actual_claim_selects_matching_trusted_source_from_multiple_sources() -> None:
    snapshot = context(
        source("meaning-1", ReflectionSourceKind.INPUT_MEANING),
        source("presentation-1", ReflectionSourceKind.PRESENTATION_FACT),
    )
    result = authority().accept(
        snapshot,
        proposal("meaning-1", "presentation-1", predicate="actual_speech"),
        support("meaning-1", "presentation-1"),
    )

    assert result.candidate is not None
    assert result.candidate.claims_actual_speech


@pytest.mark.parametrize(
    ("relation", "expected"),
    [
        (ReflectionSupportRelation.UNSUPPORTED, ReflectionCandidateStatus.REJECTED_UNSUPPORTED),
        (ReflectionSupportRelation.AMBIGUOUS, ReflectionCandidateStatus.REJECTED_AMBIGUOUS),
        (ReflectionSupportRelation.CONTRADICTED, ReflectionCandidateStatus.REJECTED_CONTRADICTED),
        (ReflectionSupportRelation.PARTIALLY_SUPPORTED, ReflectionCandidateStatus.REJECTED_POLICY),
    ],
)
def test_open_ended_durable_candidate_fails_closed_without_supported_observation(
    relation: ReflectionSupportRelation,
    expected: ReflectionCandidateStatus,
) -> None:
    snapshot = context(source("fact-1", ReflectionSourceKind.PRESENTATION_FACT))

    result = authority().accept(snapshot, proposal("fact-1"), support("fact-1", relation=relation))
    assert result.status is expected


def test_support_must_ground_to_frozen_snapshot_not_proposal_rationale() -> None:
    snapshot = context(source("fact-1", ReflectionSourceKind.PRESENTATION_FACT))

    result = authority().accept(snapshot, proposal("fact-1"), support("rationale-only"))

    assert result.status is ReflectionCandidateStatus.REJECTED_INVALID_PROVENANCE
    assert result.candidate is None


def test_retracted_source_and_related_memory_revision_drift_are_stale() -> None:
    retracted = context(source("fact-1", ReflectionSourceKind.PRESENTATION_FACT, retracted=True))
    hint = ReflectionRelationHint("memory-1", 1, MemoryRelationKind.REFINES, ("fact-2",), 0.8)
    drifted = context(source("fact-2", ReflectionSourceKind.PRESENTATION_FACT))

    assert authority().accept(retracted, proposal("fact-1"), support("fact-1")).status is (
        ReflectionCandidateStatus.REJECTED_STALE
    )
    drifted_result = authority().accept(
        drifted,
        proposal("fact-2", relation_hints=(hint,)),
        support("fact-2"),
    )
    assert drifted_result.status is (
        ReflectionCandidateStatus.REJECTED_STALE
    )


def test_accepted_relation_hint_is_preserved_without_direct_memory_mutation() -> None:
    snapshot = context(source("fact-1", ReflectionSourceKind.PRESENTATION_FACT))
    hint = ReflectionRelationHint("memory-1", 2, MemoryRelationKind.REFINES, ("fact-1",), 0.8)

    result = authority().accept(
        snapshot,
        proposal("fact-1", relation_hints=(hint,)),
        support("fact-1"),
    )

    assert result.status is ReflectionCandidateStatus.ACCEPTED_FOR_STORE_SUBMISSION
    assert result.relation_hints == (hint,)
    imports = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("app/domain/memory_reflection").glob("*.py")
    )
    assert "app.domain.memory.authority" not in imports


def test_unrelated_current_context_drift_does_not_reject_historical_evidence() -> None:
    snapshot = context(source("fact-1", ReflectionSourceKind.PRESENTATION_FACT))
    changed_current_context = ReflectionContextSnapshot(
        snapshot.reflection_id,
        snapshot.trigger,
        snapshot.primary_sources,
        snapshot.related_memory_view,
        999,
        snapshot.memory_store_revision,
        NOW + timedelta(seconds=1),
        snapshot.trace_id,
    )

    result = authority().accept(
        changed_current_context,
        proposal("fact-1"),
        support("fact-1"),
    )
    assert result.status is (
        ReflectionCandidateStatus.ACCEPTED_FOR_STORE_SUBMISSION
    )


def test_unknown_source_and_unbounded_context_are_rejected() -> None:
    snapshot = context(source("fact-1", ReflectionSourceKind.PRESENTATION_FACT))
    with pytest.raises(ValueError):
        ReflectionSourceEvidence(
            "too-large",
            ReflectionSourceKind.INPUT_MEANING,
            "owner",
            None,
            NOW,
            {"text": "x" * 20_000},
            (),
        )

    assert authority().accept(snapshot, proposal("unknown"), support("unknown")).status is (
        ReflectionCandidateStatus.REJECTED_INVALID_PROVENANCE
    )
    with pytest.raises(ValueError):
        ReflectionContextSnapshot(
            snapshot.reflection_id,
            snapshot.trigger,
            snapshot.primary_sources,
            snapshot.related_memory_view,
            snapshot.source_context_revision,
            snapshot.memory_store_revision,
            snapshot.captured_at,
            snapshot.trace_id,
            max_estimated_tokens=4,
            estimated_tokens=5,
        )
    nested: object = "too-deep"
    for _ in range(14):
        nested = [nested]
    with pytest.raises(ValueError):
        ReflectionSourceEvidence(
            "unbounded-depth",
            ReflectionSourceKind.INPUT_MEANING,
            "owner",
            1,
            NOW,
            {"nested": nested},  # type: ignore[dict-item]
            (),
        )


@pytest.mark.parametrize(
    "kind",
    (
        MemoryKind.EPISODIC,
        MemoryKind.SEMANTIC,
        MemoryKind.RELATIONSHIP,
        MemoryKind.PREFERENCE,
        MemoryKind.ACTIVITY_SKILL,
    ),
)
def test_all_canonical_durable_memory_kinds_can_be_supported(kind: MemoryKind) -> None:
    snapshot = context(source("fact-1", ReflectionSourceKind.PRESENTATION_FACT))

    result = authority().accept(snapshot, proposal("fact-1", kind=kind), support("fact-1"))

    assert result.status is ReflectionCandidateStatus.ACCEPTED_FOR_STORE_SUBMISSION
    assert result.candidate is not None and result.candidate.memory_kind is kind


def test_unknown_memory_kind_and_unresolved_support_diagnostics_are_rejected() -> None:
    with pytest.raises(ValueError):
        MemoryCandidateProposal(
            "proposal-invalid",
            "unknown",  # type: ignore[arg-type]
            MemoryContent("episode", {"value": "remember"}),
            ("fact-1",),
            0.8,
            0.7,
            ReflectionPersistenceHint.DURABLE,
            0.6,
            MemoryTemporalState(freshness=MemoryFreshnessState.HISTORICAL),
        )
    with pytest.raises(ValueError, match="SUPPORTED observation"):
        ReflectionSupportObservation(
            "proposal-1",
            ReflectionSupportRelation.SUPPORTED,
            ("fact-1",),
            ("unresolved",),
            (),
            0.8,
        )


class FakeProposalPort:
    def __init__(
        self,
        proposals: tuple[MemoryCandidateProposal, ...],
        gate: asyncio.Event | None = None,
    ) -> None:
        self.proposals = proposals
        self.gate = gate
        self.calls = 0

    async def propose(self, _: ReflectionContextSnapshot) -> tuple[MemoryCandidateProposal, ...]:
        self.calls += 1
        if self.gate is not None:
            await self.gate.wait()
        return self.proposals


class FakeSupportPort:
    async def observe(
        self,
        _: ReflectionContextSnapshot,
        candidate: MemoryCandidateProposal,
    ) -> ReflectionSupportObservation:
        return ReflectionSupportObservation(
            candidate.proposal_id,
            ReflectionSupportRelation.SUPPORTED,
            candidate.source_refs,
            (),
            (),
            0.75,
        )


def test_zero_candidate_is_a_valid_background_result() -> None:
    async def run() -> None:
        snapshot = context(source("fact-1", ReflectionSourceKind.PRESENTATION_FACT))
        coordinator = ReflectionCoordinator(FakeProposalPort(()), FakeSupportPort(), authority())

        result = await coordinator.submit(snapshot)

        assert result.results == ()
        assert coordinator.pending_task_count == 0

    asyncio.run(run())


def test_slow_reflection_does_not_block_foreground_and_burst_coalesces() -> None:
    async def run() -> None:
        snapshot = context(source("fact-1", ReflectionSourceKind.PRESENTATION_FACT))
        gate = asyncio.Event()
        provider = FakeProposalPort((proposal("fact-1"),), gate)
        coordinator = ReflectionCoordinator(provider, FakeSupportPort(), authority())
        first = coordinator.submit(snapshot)
        second = coordinator.submit(snapshot)
        foreground = asyncio.create_task(asyncio.sleep(0))

        await foreground
        assert first is second
        assert coordinator.pending_task_count == 1
        gate.set()
        result = await first
        assert result.results[0].status is ReflectionCandidateStatus.ACCEPTED_FOR_STORE_SUBMISSION
        assert result.coalesced_source_refs == ("fact-1",)
        assert result.telemetry is not None
        assert ReflectionEventKind.COALESCED in result.telemetry.event_kinds
        assert result.telemetry.source_item_count == 1
        assert result.telemetry.proposal_count == 1
        assert result.telemetry.accepted_count == 1
        assert result.telemetry.proposal_latency_ms >= 0
        assert result.telemetry.support_latency_ms >= 0
        assert provider.calls == 1
        assert coordinator.pending_task_count == 0

    asyncio.run(run())


def test_different_immutable_context_generations_do_not_coalesce() -> None:
    async def run() -> None:
        first_context = context(source("fact-1", ReflectionSourceKind.PRESENTATION_FACT))
        second_context = context(
            source("fact-1", ReflectionSourceKind.PRESENTATION_FACT, revision=2)
        )
        gate = asyncio.Event()
        provider = FakeProposalPort((proposal("fact-1"),), gate)
        coordinator = ReflectionCoordinator(provider, FakeSupportPort(), authority())

        first = coordinator.submit(first_context)
        second = coordinator.submit(second_context)
        await asyncio.sleep(0)

        assert first is not second
        gate.set()
        await asyncio.gather(first, second)
        assert provider.calls == 2

    asyncio.run(run())


def test_live_retracted_source_after_provider_await_is_rejected_as_stale() -> None:
    async def run() -> None:
        captured = context(source("fact-1", ReflectionSourceKind.PRESENTATION_FACT))
        retracted = context(
            source("fact-1", ReflectionSourceKind.PRESENTATION_FACT, retracted=True)
        )
        coordinator = ReflectionCoordinator(
            FakeProposalPort((proposal("fact-1"),)),
            FakeSupportPort(),
            authority(),
            live_context=lambda _: retracted,
        )

        result = await coordinator.submit(captured)

        assert result.results[0].status is ReflectionCandidateStatus.REJECTED_STALE

    asyncio.run(run())


def test_maximum_proposals_have_bounded_aggregate_telemetry() -> None:
    async def run() -> None:
        snapshot = context(source("fact-1", ReflectionSourceKind.PRESENTATION_FACT))
        proposals = tuple(
            replace(proposal("fact-1"), proposal_id=f"proposal-{index}")
            for index in range(32)
        )
        coordinator = ReflectionCoordinator(
            FakeProposalPort(proposals), FakeSupportPort(), authority()
        )

        result = await coordinator.submit(snapshot)

        assert result.telemetry is not None
        assert result.telemetry.proposal_count == 32
        assert len(result.telemetry.event_kinds) <= 64

    asyncio.run(run())


def test_cancelled_background_reflection_leaves_no_pending_task() -> None:
    async def run() -> None:
        snapshot = context(source("fact-1", ReflectionSourceKind.PRESENTATION_FACT))
        coordinator = ReflectionCoordinator(
            FakeProposalPort((proposal("fact-1"),), asyncio.Event()),
            FakeSupportPort(),
            authority(),
        )
        coordinator.submit(snapshot)
        await asyncio.sleep(0)
        await coordinator.cancel(snapshot)

        assert coordinator.pending_task_count == 0

    asyncio.run(run())


def test_background_queue_pressure_is_typed_and_does_not_start_another_provider_call() -> None:
    async def run() -> None:
        first_snapshot = context(source("fact-1", ReflectionSourceKind.PRESENTATION_FACT))
        second_snapshot = context(source("fact-2", ReflectionSourceKind.PRESENTATION_FACT))
        gate = asyncio.Event()
        provider = FakeProposalPort((proposal("fact-1"),), gate)
        coordinator = ReflectionCoordinator(
            provider,
            FakeSupportPort(),
            authority(),
            max_pending_tasks=1,
        )

        first = coordinator.submit(first_snapshot)
        await asyncio.sleep(0)
        deferred = await coordinator.submit(second_snapshot)

        assert deferred.results[0].status is ReflectionCandidateStatus.DEFERRED_QUEUE_PRESSURE
        assert deferred.telemetry is not None
        assert ReflectionEventKind.DEFERRED in deferred.telemetry.event_kinds
        assert provider.calls == 1
        gate.set()
        await first

    asyncio.run(run())


def test_provider_unavailable_creates_typed_failure_without_candidate() -> None:
    class UnavailableProposalPort:
        async def propose(
            self, _: ReflectionContextSnapshot
        ) -> tuple[MemoryCandidateProposal, ...]:
            raise RuntimeError("unavailable")

    async def run() -> None:
        snapshot = context(source("fact-1", ReflectionSourceKind.PRESENTATION_FACT))
        coordinator = ReflectionCoordinator(
            UnavailableProposalPort(),
            FakeSupportPort(),
            authority(),
        )

        result = await coordinator.submit(snapshot)

        assert result.results[0].status is ReflectionCandidateStatus.REFLECTION_PROVIDER_UNAVAILABLE
        assert result.results[0].candidate is None

    asyncio.run(run())


def test_support_provider_unavailable_fails_closed_for_open_ended_candidate() -> None:
    snapshot = context(source("fact-1", ReflectionSourceKind.PRESENTATION_FACT))

    result = authority().accept(snapshot, proposal("fact-1"), None)

    assert result.status is ReflectionCandidateStatus.SUPPORT_PROVIDER_UNAVAILABLE
    assert result.candidate is None


def test_deterministic_capture_requires_closed_fact_source_and_keeps_current_state_immutable(
) -> None:
    state_payload = {"energy": 0.6}
    state_source = ReflectionSourceEvidence(
        "state-1",
        ReflectionSourceKind.INTERNAL_STATE_TRANSITION,
        "appraisal",
        1,
        NOW,
        state_payload,
        ("state-transition-1",),
    )
    snapshot = context(state_source)

    rejected = authority().accept_trusted_deterministic_capture(
        snapshot, proposal("state-1", deterministic_capture=True)
    )

    assert rejected.status is ReflectionCandidateStatus.REJECTED_POLICY
    assert state_payload == {"energy": 0.6}


def test_provider_deterministic_flag_cannot_skip_support_observation() -> None:
    snapshot = context(source("fact-1", ReflectionSourceKind.PRESENTATION_FACT))

    result = authority().accept(
        snapshot, proposal("fact-1", deterministic_capture=True), None
    )

    assert result.status is ReflectionCandidateStatus.SUPPORT_PROVIDER_UNAVAILABLE


def test_accepted_candidate_is_submission_only_and_does_not_claim_store_success() -> None:
    snapshot = context(source("fact-1", ReflectionSourceKind.PRESENTATION_FACT))

    result = authority().accept(snapshot, proposal("fact-1"), support("fact-1"))

    assert result.status is ReflectionCandidateStatus.ACCEPTED_FOR_STORE_SUBMISSION
    assert result.candidate is not None
    assert not hasattr(result, "memory_id")
    assert not hasattr(result, "disposition")
