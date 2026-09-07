import json
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest

from app.domain.appraisal import (
    AppraisalCandidate,
    AppraisalFactsSnapshot,
    AppraisalPath,
    DecayDiagnosticCode,
    DecayFacetRule,
    DecayPolicy,
    DecayTargetScope,
    FacetRef,
    InternalStateFacet,
    InternalStateReducer,
    InternalStateSnapshot,
    LifecycleAppraisalInput,
    LifecycleKind,
    StateDeltaProposal,
    StateFacetKind,
    decay_candidate,
    freeze_appraisal_facts,
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


def decay_policy(*rules: DecayFacetRule, revision: int = 1) -> DecayPolicy:
    return DecayPolicy("yura.appraisal.decay", revision, rules)


def rule(
    rule_id: str,
    state_key: str | None,
    *,
    baseline: float = 0.0,
    half_life_seconds: float = 10.0,
    minimum_elapsed_seconds: float = 0.0,
    scope: DecayTargetScope = DecayTargetScope.GLOBAL,
) -> DecayFacetRule:
    return DecayFacetRule(
        rule_id,
        StateFacetKind.EMOTION,
        state_key,
        scope,
        baseline,
        half_life_seconds,
        minimum_elapsed_seconds,
    )


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


def test_appraisal_facts_freeze_candidate_at_a_matching_state_revision() -> None:
    state = snapshot(facet())
    facts = freeze_appraisal_facts(
        candidate(proposal()), state, revision=4, captured_at=NOW + timedelta(seconds=2)
    )
    assert facts.internal_state_revision == state.revision
    assert facts.source_event_ids == ("event:1",)
    assert facts.evidence_refs == ("rule:1",)
    assert facts.to_dict()["revision"] == 4


def test_appraisal_facts_reject_stale_candidate_and_unbounded_evidence() -> None:
    with pytest.raises(ValueError, match="state revision"):
        freeze_appraisal_facts(
            candidate(proposal(), base=2),
            snapshot(facet()),
            revision=4,
            captured_at=NOW + timedelta(seconds=2),
        )
    with pytest.raises(ValueError, match="bounded maximum"):
        AppraisalFactsSnapshot(
            4,
            7,
            3,
            ("event:1",),
            (),
            0.7,
            0.8,
            tuple(f"evidence:{index}" for index in range(17)),
            NOW + timedelta(seconds=2),
        )


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
    policy = decay_policy(rule("joy", "joy"))
    first = decay_candidate(
        state,
        policy,
        candidate_id="decay:1",
        source_event_id="timer:1",
        source_context_revision=7,
        evaluated_at=NOW + timedelta(seconds=10),
    )
    second = decay_candidate(
        state,
        policy,
        candidate_id="decay:2",
        source_event_id="timer:1",
        source_context_revision=7,
        evaluated_at=NOW + timedelta(seconds=10),
    )
    assert first.proposals[0].delta == pytest.approx(-0.4)
    assert first.proposals[0].delta == second.proposals[0].delta
    assert first.proposals[0].decay_provenance is not None
    assert first.proposals[0].decay_provenance.elapsed_seconds == 10.0


def test_decay_two_half_lives_and_both_sides_converge_monotonically_to_baseline() -> None:
    policy = decay_policy(rule("joy", "joy", half_life_seconds=10))
    for value in (0.8, -0.8):
        state = snapshot(facet(value=value))
        one_half_life = decay_candidate(
            state,
            policy,
            candidate_id="decay:one",
            source_event_id="timer:1",
            source_context_revision=7,
            evaluated_at=NOW + timedelta(seconds=10),
        )
        two_half_lives = decay_candidate(
            state,
            policy,
            candidate_id="decay:two",
            source_event_id="timer:1",
            source_context_revision=7,
            evaluated_at=NOW + timedelta(seconds=20),
        )
        after_one = value + one_half_life.proposals[0].delta
        after_two = value + two_half_lives.proposals[0].delta
        assert after_two == pytest.approx(value / 4)
        assert abs(after_two) < abs(after_one) < abs(value)


def test_resume_uses_absolute_elapsed_not_lifecycle_downtime_without_fixed_preset() -> None:
    state = snapshot(facet(value=0.8), facet(FEAR, 0.6))
    lifecycle = LifecycleAppraisalInput(
        "lifecycle:resume",
        LifecycleKind.RESUME,
        8,
        NOW + timedelta(hours=1),
        7,
    )
    result = lifecycle_candidate(
        state,
        lifecycle,
        decay_policy(
            rule("joy", "joy", half_life_seconds=3600),
            rule("fear", "fear", baseline=0.1, half_life_seconds=1800),
        ),
        candidate_id="resume:1",
    )
    assert result.path is AppraisalPath.LIFECYCLE
    assert result.proposals[0].delta == pytest.approx(-0.4)
    assert result.proposals[1].delta == pytest.approx(-0.375)
    assert all(
        item.facet_ref.state_key not in {"neutral", "awakening"} for item in result.proposals
    )
    assert all(
        item.decay_provenance is not None and item.decay_provenance.elapsed_seconds == 3600
        for item in result.proposals
    )


def test_decay_rule_selection_missing_rule_and_policy_unavailable_fail_closed() -> None:
    state = snapshot(facet(JOY, 0.8), facet(FEAR, -0.8))
    selected = decay_candidate(
        state,
        decay_policy(rule("emotion-default", None, half_life_seconds=10)),
        candidate_id="decay:rule",
        source_event_id="timer:1",
        source_context_revision=7,
        evaluated_at=NOW + timedelta(seconds=10),
    )
    assert len(selected.proposals) == 2
    assert all(item.decay_provenance is not None for item in selected.proposals)
    assert all(
        item.decay_provenance.decay_rule_id == "emotion-default"
        for item in selected.proposals
        if item.decay_provenance
    )

    missing = decay_candidate(
        state,
        decay_policy(rule("joy", "joy", minimum_elapsed_seconds=20)),
        candidate_id="decay:missing",
        source_event_id="timer:1",
        source_context_revision=7,
        evaluated_at=NOW + timedelta(seconds=10),
    )
    assert missing.proposals == ()
    assert missing.diagnostics[0].code is DecayDiagnosticCode.POLICY_RULE_MISSING
    assert missing.diagnostics[0].facet_ref == FEAR

    unavailable = decay_candidate(
        snapshot(facet(value=0.8)),
        None,
        candidate_id="decay:unavailable",
        source_event_id="timer:1",
        source_context_revision=7,
        evaluated_at=NOW + timedelta(seconds=10),
    )
    assert unavailable.proposals == ()
    assert unavailable.diagnostics[0].code is DecayDiagnosticCode.POLICY_UNAVAILABLE
    with pytest.raises(ValueError, match="重複"):
        decay_policy(rule("one", "joy"), rule("two", "joy"))


def test_exact_rule_precedence_and_scope_separation_are_fail_closed() -> None:
    exact = decay_candidate(
        snapshot(facet(JOY, 0.8)),
        decay_policy(
            rule("emotion-default", None, half_life_seconds=20),
            rule("joy-exact", "joy", half_life_seconds=10),
        ),
        candidate_id="decay:precedence",
        source_event_id="timer:1",
        source_context_revision=7,
        evaluated_at=NOW + timedelta(seconds=10),
    )
    assert exact.proposals[0].decay_provenance is not None
    assert exact.proposals[0].decay_provenance.decay_rule_id == "joy-exact"

    targeted_joy = FacetRef(StateFacetKind.EMOTION, "joy", "person:1")
    targeted_with_global_only = decay_candidate(
        snapshot(facet(targeted_joy, 0.8)),
        decay_policy(rule("joy-global", "joy")),
        candidate_id="decay:global-only",
        source_event_id="timer:1",
        source_context_revision=7,
        evaluated_at=NOW + timedelta(seconds=10),
    )
    global_with_targeted_only = decay_candidate(
        snapshot(facet(JOY, 0.8)),
        decay_policy(
            DecayFacetRule(
                "joy-targeted",
                StateFacetKind.EMOTION,
                "joy",
                DecayTargetScope.TARGETED,
                0.0,
                10.0,
                0.0,
            )
        ),
        candidate_id="decay:targeted-only",
        source_event_id="timer:1",
        source_context_revision=7,
        evaluated_at=NOW + timedelta(seconds=10),
    )
    for candidate in (targeted_with_global_only, global_with_targeted_only):
        assert candidate.proposals == ()
        assert candidate.diagnostics[0].code is DecayDiagnosticCode.POLICY_RULE_MISSING


def test_reducer_rejects_old_decay_policy_without_rebinding_provenance() -> None:
    current_policy = decay_policy(rule("joy", "joy"), revision=2)
    old_candidate = decay_candidate(
        snapshot(facet(value=0.8)),
        decay_policy(rule("joy", "joy"), revision=1),
        candidate_id="decay:old",
        source_event_id="timer:1",
        source_context_revision=7,
        evaluated_at=NOW + timedelta(seconds=10),
    )
    with pytest.raises(ValueError, match="方針が古く"):
        InternalStateReducer(snapshot(facet(value=0.8))).commit(
            old_candidate,
            current_source_context_revision=7,
            committed_at=NOW + timedelta(seconds=11),
            current_decay_policy=current_policy,
        )


def test_reducer_rejects_stale_decay_state_and_source_revisions() -> None:
    policy = decay_policy(rule("joy", "joy"))
    original = snapshot(facet(value=0.8))
    stale = decay_candidate(
        original,
        policy,
        candidate_id="decay:stale",
        source_event_id="timer:1",
        source_context_revision=7,
        evaluated_at=NOW + timedelta(seconds=10),
    )
    newer_state = InternalStateSnapshot(4, 7, original.facets, NOW)
    with pytest.raises(ValueError, match="stale for current state"):
        InternalStateReducer(newer_state).commit(
            stale,
            current_source_context_revision=7,
            committed_at=NOW + timedelta(seconds=11),
            current_decay_policy=policy,
        )
    with pytest.raises(ValueError, match="stale for source context"):
        InternalStateReducer(original).commit(
            stale,
            current_source_context_revision=8,
            committed_at=NOW + timedelta(seconds=11),
            current_decay_policy=policy,
        )


def test_targeted_rule_numeric_rejection_and_noop_are_explicit() -> None:
    targeted_rule = DecayFacetRule(
        "interest-targeted",
        StateFacetKind.INTEREST,
        "curiosity",
        DecayTargetScope.TARGETED,
        0.0,
        10.0,
        0.0,
    )
    targeted = decay_candidate(
        snapshot(facet(INTEREST, 0.8)),
        decay_policy(targeted_rule),
        candidate_id="decay:targeted",
        source_event_id="timer:1",
        source_context_revision=7,
        evaluated_at=NOW + timedelta(seconds=10),
    )
    assert targeted.proposals[0].facet_ref == INTEREST
    assert targeted.proposals[0].delta == pytest.approx(-0.4)

    noop = decay_candidate(
        snapshot(facet(value=0.0)),
        decay_policy(rule("joy", "joy")),
        candidate_id="decay:noop",
        source_event_id="timer:1",
        source_context_revision=7,
        evaluated_at=NOW + timedelta(seconds=10),
    )
    assert noop.proposals == ()
    with pytest.raises(ValueError, match="half_life"):
        rule("bad", "joy", half_life_seconds=cast(Any, True))


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_decay_rule_rejects_non_finite_values_for_every_numeric_field(bad: float) -> None:
    with pytest.raises(ValueError):
        rule("bad-baseline", "joy", baseline=bad)
    with pytest.raises(ValueError):
        rule("bad-half-life", "joy", half_life_seconds=bad)
    with pytest.raises(ValueError):
        rule("bad-minimum", "joy", minimum_elapsed_seconds=bad)
