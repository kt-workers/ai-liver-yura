import json
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest

from app.domain.appraisal import (
    AppraisalCandidate,
    AppraisalPath,
    DecayPolicy,
    FacetRef,
    InternalStateFacet,
    InternalStateReducer,
    InternalStateSnapshot,
    LifecycleAppraisalInput,
    LifecycleKind,
    StateDeltaProposal,
    StateFacetKind,
    decay_candidate,
    lifecycle_candidate,
)

NOW = datetime(2026, 8, 24, tzinfo=timezone.utc)
JOY = FacetRef(StateFacetKind.EMOTION, "joy")
FEAR = FacetRef(StateFacetKind.EMOTION, "fear")
INTEREST = FacetRef(StateFacetKind.INTEREST, "curiosity", "topic:sea")


def facet(ref: FacetRef = JOY, value: float = 0.4) -> InternalStateFacet:
    return InternalStateFacet(ref, value, 0.0, value, 0.8, ("event:seed",), NOW)


def snapshot(*facets: InternalStateFacet) -> InternalStateSnapshot:
    return InternalStateSnapshot(3, 7, facets, NOW)


def candidate(
    *proposals: StateDeltaProposal, base: int = 3, context: int = 7
) -> AppraisalCandidate:
    return AppraisalCandidate(
        "candidate:1",
        ("event:1",),
        context,
        base,
        AppraisalPath.FAST_DETERMINISTIC,
        (),
        proposals,
        0.7,
        0.8,
        ("rule:1",),
        NOW + timedelta(seconds=1),
    )


def proposal(ref: FacetRef = JOY, delta: float = 0.2) -> StateDeltaProposal:
    return StateDeltaProposal(ref, delta, 0.9, ("event:1",))


def test_reducer_is_only_immutable_state_transition_authority() -> None:
    before = snapshot(facet())
    reducer = InternalStateReducer(before)
    after = reducer.commit(
        candidate(proposal()),
        current_source_context_revision=7,
        committed_at=NOW + timedelta(seconds=2),
    )
    assert before.facets[0].current == 0.4
    assert after.revision == 4
    assert after.facets[0].current == pytest.approx(0.6)
    assert after.facets[0].previous == 0.4
    assert after.facets[0].last_delta == 0.2
    assert after.facets[0].cause_refs == ("event:1",)
    with pytest.raises(FrozenInstanceError):
        after.facets[0].current = 1.0  # type: ignore[misc]
    json.dumps(after.to_dict(), allow_nan=False)


def test_conflicting_affects_can_coexist_without_overwriting_each_other() -> None:
    reducer = InternalStateReducer(snapshot(facet()))
    after = reducer.commit(
        candidate(proposal(JOY, 0.1), proposal(FEAR, 0.5)),
        current_source_context_revision=7,
        committed_at=NOW + timedelta(seconds=2),
    )
    values = {item.ref: item.current for item in after.facets}
    assert values[JOY] == pytest.approx(0.5)
    assert values[FEAR] == pytest.approx(0.5)


def test_competing_candidates_from_same_revision_cannot_both_commit() -> None:
    reducer = InternalStateReducer(snapshot(facet(value=0.2)))
    first = candidate(proposal(JOY, 0.1))
    second = candidate(proposal(JOY, -0.1))
    committed = reducer.commit(
        first,
        current_source_context_revision=7,
        committed_at=NOW + timedelta(seconds=2),
    )
    assert committed.revision == 4
    with pytest.raises(ValueError, match="stale for current state"):
        reducer.commit(
            second,
            current_source_context_revision=7,
            committed_at=NOW + timedelta(seconds=2),
        )
    assert reducer.snapshot() is committed


def test_interest_and_relationship_require_target_identity() -> None:
    with pytest.raises(ValueError, match="require target_ref"):
        FacetRef(StateFacetKind.INTEREST, "curiosity")
    with pytest.raises(ValueError, match="require target_ref"):
        FacetRef(StateFacetKind.RELATIONSHIP, "trust")
    assert INTEREST.target_ref == "topic:sea"


@pytest.mark.parametrize(
    ("bad_candidate", "message"),
    [
        (candidate(proposal(), base=2), "stale for current state"),
        (candidate(proposal(), context=6), "stale for source context"),
        (candidate(proposal(JOY, 0.8)), "outside allowed range"),
        (candidate(), "at least one delta"),
    ],
)
def test_invalid_or_stale_state_delta_is_rejected(
    bad_candidate: AppraisalCandidate, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        InternalStateReducer(snapshot(facet())).commit(
            bad_candidate,
            current_source_context_revision=7,
            committed_at=NOW + timedelta(seconds=2),
        )


def test_duplicate_proposals_and_non_finite_values_are_rejected() -> None:
    with pytest.raises(ValueError, match="proposal refs must be unique"):
        candidate(proposal(), proposal())
    with pytest.raises(ValueError, match="between"):
        StateDeltaProposal(JOY, float("nan"), 0.8, ("event:1",))
    with pytest.raises(ValueError, match="must not be zero"):
        StateDeltaProposal(JOY, 0.0, 0.8, ("event:1",))


def test_untyped_enum_nested_contract_and_collection_shapes_are_rejected() -> None:
    with pytest.raises(ValueError, match="StateFacetKind"):
        FacetRef(cast(Any, "emotion"), "joy")
    with pytest.raises(ValueError, match="facets must contain"):
        InternalStateSnapshot(0, 0, cast(Any, ("not-a-facet",)), NOW)
    with pytest.raises(ValueError, match="path must be"):
        AppraisalCandidate(
            "candidate:bad",
            ("event:1",),
            0,
            0,
            cast(Any, "deep_llm"),
            (),
            (),
            0.0,
            0.0,
            (),
            NOW,
        )
    with pytest.raises(ValueError, match="must be an array"):
        StateDeltaProposal(JOY, 0.1, 0.8, cast(Any, "event:1"))


def test_delta_cause_must_be_grounded_in_candidate_source_or_evidence() -> None:
    ungrounded = candidate(StateDeltaProposal(JOY, 0.1, 0.8, ("invented:cause",)))
    with pytest.raises(ValueError, match="outside candidate evidence"):
        InternalStateReducer(snapshot(facet())).commit(
            ungrounded,
            current_source_context_revision=7,
            committed_at=NOW + timedelta(seconds=2),
        )


def test_candidate_cannot_predate_current_state() -> None:
    stale_time = candidate(proposal())
    old = AppraisalCandidate(
        stale_time.candidate_id,
        stale_time.source_event_ids,
        stale_time.source_context_revision,
        stale_time.base_state_revision,
        stale_time.path,
        stale_time.dimensions,
        stale_time.proposals,
        stale_time.salience,
        stale_time.relevance,
        stale_time.evidence_refs,
        NOW - timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="candidate timestamp"):
        InternalStateReducer(snapshot(facet())).commit(
            old,
            current_source_context_revision=7,
            committed_at=NOW + timedelta(seconds=2),
        )


def test_decay_is_deterministic_from_elapsed_time_and_half_life() -> None:
    state = snapshot(facet(value=0.8))
    policy = (DecayPolicy(JOY, 0.0, 10.0),)
    first = decay_candidate(
        state,
        policy,
        candidate_id="decay:1",
        source_event_id="timer:1",
        source_context_revision=7,
        elapsed_seconds=10.0,
        created_at=NOW + timedelta(seconds=10),
    )
    second = decay_candidate(
        state,
        policy,
        candidate_id="decay:2",
        source_event_id="timer:1",
        source_context_revision=7,
        elapsed_seconds=10.0,
        created_at=NOW + timedelta(seconds=10),
    )
    assert first.proposals[0].delta == pytest.approx(-0.4)
    assert first.proposals[0].delta == second.proposals[0].delta


def test_resume_uses_previous_state_and_downtime_without_fixed_preset() -> None:
    state = snapshot(facet(value=0.8), facet(FEAR, 0.6))
    lifecycle = LifecycleAppraisalInput(
        "lifecycle:resume",
        LifecycleKind.RESUME,
        8,
        NOW + timedelta(hours=1),
        3600,
    )
    result = lifecycle_candidate(
        state,
        lifecycle,
        (DecayPolicy(JOY, 0.0, 3600), DecayPolicy(FEAR, 0.1, 1800)),
        candidate_id="resume:1",
    )
    assert result.path is AppraisalPath.LIFECYCLE
    assert result.proposals[0].delta == pytest.approx(-0.4)
    assert result.proposals[1].delta == pytest.approx(-0.375)
    assert all(
        item.facet_ref.state_key not in {"neutral", "awakening"} for item in result.proposals
    )
