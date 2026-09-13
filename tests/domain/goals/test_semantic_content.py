"""CREATE意味内容の保存・再公開と既存Fenceによる現在性の検証。"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
from typing import Any

import pytest

from app.domain.contracts.finalization import (
    AuthorityFinalizationFence,
    AuthorityFinalizationParticipant,
    AuthorityFinalizationRequest,
    FinalizationFailure,
)
from app.domain.executive import (
    CommitmentTransitionOperation as C,
)
from app.domain.executive import (
    CommitmentTransitionPayload,
    ExecutiveOutcome,
    GoalTransitionPayload,
)
from app.domain.executive import (
    GoalTransitionOperation as G,
)
from app.domain.executive.deliberator import OUTPUT_SCHEMA, parse_candidate
from app.domain.goal_commitment_semantics import (
    GoalCommitmentSemanticCertainty as Certainty,
)
from app.domain.goal_commitment_semantics import (
    GoalCommitmentSemanticModality as Modality,
)
from app.domain.goal_commitment_semantics import (
    GoalCommitmentSemanticPolarity as Polarity,
)
from app.domain.goal_commitment_semantics import (
    GoalCommitmentSemanticSpec,
)
from app.domain.goal_commitment_semantics import (
    GoalCommitmentSemanticSubjectKind as Subject,
)
from app.domain.goals import GoalCommitmentSnapshot, GoalCommitmentStore
from tests.domain.goals.test_goal_commitment_store import (
    NOW,
    commitment_transition,
    decision,
    goal_transition,
)
from tests.helpers.goal_semantics import semantic_spec


@pytest.mark.parametrize("kind", ["goal", "commitment"])
def test_create_and_later_publication_without_original_snapshot(kind: str) -> None:
    store = GoalCommitmentStore()
    if kind == "goal":
        transition = goal_transition(G.CREATE, 0)
        store.apply(decision("create", 0, goals=(transition,)))
        publication = store.goal_semantic_publication("goal-1")
    else:
        transition_c = commitment_transition(C.CREATE, 0)
        store.apply(decision("create", 0, commitments=(transition_c,)))
        publication = store.commitment_semantic_publication("commitment-1")
    assert publication is not None
    view = publication.value
    assert view.state_revision == 1 and view.semantic_revision == 1
    assert view.modality.value == kind and view.state_kind == view.modality
    assert view.certainty is Certainty.CERTAIN
    assert view.source_decision_id == "create"
    assert view.semantic_ref == view.semantic_spec.semantic_ref
    assert view.reason_refs == (("reason-goal-1",) if kind == "goal" else ("reason-commitment-1",))
    assert view.source_event_ids == (() if kind == "goal" else ("event-create",))
    if kind == "goal":
        assert view.created_from_decision_id == "create"
        assert view.motivation_refs == ("reason-goal-1",)
    later = GoalCommitmentStore(store.snapshot())
    retrieved = (
        later.goal_semantic_publication("goal-1")
        if kind == "goal"
        else later.commitment_semantic_publication("commitment-1")
    )
    assert retrieved is not None and retrieved.value == view
    assert later.goal_semantic_publication("absent") is None
    assert later.commitment_semantic_publication("absent") is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("semantic_revision", 0),
        ("semantic_revision", True),
        ("semantic_revision", 2),
        ("predicate", ""),
        ("predicate", 4),
        ("polarity", "affirm"),
        ("polarity", None),
        ("degree", True),
        ("degree", 10**400),
        ("degree", -0.1),
        ("degree", 1.1),
        ("degree", float("nan")),
        ("degree", float("inf")),
        ("value", {1: "x"}),
        ("value", float("nan")),
        ("value", object()),
        ("subject_kind", "self"),
        ("subject_ref", "self"),
    ],
)
def test_spec_rejects_invalid_structure(field: str, value: Any) -> None:
    with pytest.raises((ValueError, TypeError)):
        replace(semantic_spec("s"), **{field: value})


def test_reference_subject_and_strict_closed_parser() -> None:
    spec = replace(
        semantic_spec("s"),
        subject_kind=Subject.REFERENCE,
        subject_ref="fact-x",
        polarity=Polarity.NEGATE,
        degree=0.5,
    )
    assert GoalCommitmentSemanticSpec.from_dict(spec.to_dict()) == spec
    with pytest.raises(ValueError):
        replace(spec, subject_ref=None)
    for field in ("rationale", "raw_user_text", "prompt"):
        with pytest.raises(ValueError):
            GoalCommitmentSemanticSpec.from_dict({**spec.to_dict(), field: "text"})
    data: dict[str, Any] = {"nested": [1]}
    frozen = replace(spec, value=data)
    data["nested"].append(2)
    assert frozen.to_dict()["value"] == {"nested": [1]}


@pytest.mark.parametrize("kind", ["goal", "commitment"])
def test_create_requires_exact_matching_spec_and_noncreate_forbids_it(kind: str) -> None:
    if kind == "goal":
        payload = goal_transition(G.CREATE, 0).payload
        for wrong in (None, semantic_spec("wrong")):
            with pytest.raises(ValueError):
                replace(payload, semantic_goal_spec=wrong).validate_for(G.CREATE)
        for operation in G:
            if operation is not G.CREATE:
                with pytest.raises(ValueError):
                    GoalTransitionPayload(semantic_goal_spec=semantic_spec("s")).validate_for(
                        operation
                    )
    else:
        payload_c = commitment_transition(C.CREATE, 0).payload
        for wrong in (None, semantic_spec("wrong")):
            with pytest.raises(ValueError):
                replace(payload_c, semantic_commitment_spec=wrong).validate_for(C.CREATE)
        for operation_c in C:
            if operation_c is not C.CREATE:
                with pytest.raises(ValueError):
                    CommitmentTransitionPayload(
                        semantic_commitment_spec=semantic_spec("s")
                    ).validate_for(operation_c)


def test_cross_state_semantic_identity_collision_is_atomic() -> None:
    store = GoalCommitmentStore()
    goal = goal_transition(G.CREATE, 0)
    spec = goal.payload.semantic_goal_spec
    assert spec is not None
    commitment = commitment_transition(C.CREATE, 0)
    commitment = replace(
        commitment,
        payload=replace(
            commitment.payload,
            semantic_commitment_ref=spec.semantic_ref,
            semantic_commitment_spec=replace(spec, polarity=Polarity.NEGATE),
        ),
    )
    with pytest.raises(ValueError, match="semantic identity"):
        store.apply(decision("collision", 0, goals=(goal,), commitments=(commitment,)))
    assert store.snapshot().revision == 0
    store.apply(decision("goal", 0, goals=(goal,)))
    initial = store.snapshot()
    forged = replace(
        initial.goals[0],
        goal_id="other",
        semantic_goal_spec=replace(spec, value={"different": True}),
    )
    with pytest.raises(ValueError, match="semantic identity"):
        GoalCommitmentStore(replace(initial, goals=initial.goals + (forged,)))


@pytest.mark.parametrize("kind", ["goal", "commitment"])
def test_lifecycle_exact_content_and_concurrent_stale_fence(kind: str) -> None:
    store = GoalCommitmentStore()
    if kind == "goal":
        store.apply(decision("create", 0, goals=(goal_transition(G.CREATE, 0),)))
        original = store.goal_semantic_publication("goal-1")
        ops = (G.ACTIVATE, G.REPRIORITIZE, G.SUSPEND, G.RESUME, G.COMPLETE)
        for rev, op in enumerate(ops, 1):
            store.apply(decision(str(rev), rev, goals=(goal_transition(op, rev),)))
        current = store.goal_semantic_publication("goal-1")
    else:
        store.apply(decision("create", 0, commitments=(commitment_transition(C.CREATE, 0),)))
        original = store.commitment_semantic_publication("commitment-1")
        with ThreadPoolExecutor(max_workers=1) as pool:
            for rev, op_c in enumerate((C.ACTIVATE, C.SUSPEND, C.RESUME, C.FULFILL), 1):
                pool.submit(
                    store.apply,
                    decision(str(rev), rev, commitments=(commitment_transition(op_c, rev),)),
                ).result()
        current = store.commitment_semantic_publication("commitment-1")
    assert original is not None and current is not None
    assert original.value.semantic_spec == current.value.semantic_spec
    assert original.value.state_revision < current.value.state_revision
    assert original.value.state_revision == 1

    class Consumer:
        def __init__(self) -> None:
            self.participant = AuthorityFinalizationParticipant(self, "test-semantic-consumer", 90)

        def accept(self, value: int, now: datetime) -> int:
            return value

    consumer = Consumer()
    operation = consumer.participant.register_operation(consumer, "accept", consumer.accept)
    fence = AuthorityFinalizationFence()
    stale = fence.finalize(
        AuthorityFinalizationRequest(original.tokens, consumer.participant, operation, 1)
    )
    assert stale.failure is FinalizationFailure.GENERATION_MISMATCH
    fresh = fence.finalize(
        AuthorityFinalizationRequest(current.tokens, consumer.participant, operation, 1)
    )
    assert fresh.failure is None and fresh.value == 1


@pytest.mark.parametrize("kind", ["goal", "commitment"])
@pytest.mark.parametrize("unknown", [False, True])
def test_real_executive_create_to_store_publication(kind: str, unknown: bool) -> None:
    from tests.domain.executive.test_executive import NOW as EXEC_NOW
    from tests.domain.executive.test_executive import candidate, live_state, snapshot
    from tests.helpers.executive_requirements import fence_clock, make_authority

    context = snapshot()
    reference = "unknown-ref" if unknown else "fact-desire"
    store = GoalCommitmentStore(GoalCommitmentSnapshot(5, (), (), EXEC_NOW))
    proposed = replace(candidate(), outcome=ExecutiveOutcome.CONTINUE_ACTIVITY, intents=())
    if kind == "goal":
        t = goal_transition(G.CREATE, 5, goal_id="goal-spec")
        spec = replace(
            semantic_spec("semantic-goal"), subject_kind=Subject.REFERENCE, subject_ref=reference
        )
        t = replace(
            t,
            payload=GoalTransitionPayload(
                "semantic-goal",
                50,
                goal_kind="general",
                interruption_policy="resumable",
                semantic_goal_spec=spec,
            ),
            reason_refs=("fact-desire",),
        )
        proposed = replace(proposed, goal_transition_intents=(t,))
    else:
        c = commitment_transition(C.CREATE, 5, commitment_id="commitment-spec")
        spec = replace(
            semantic_spec("commitment-spec"), subject_kind=Subject.REFERENCE, subject_ref=reference
        )
        c = replace(
            c,
            payload=CommitmentTransitionPayload(
                "commitment-spec", strength=50, priority=50, semantic_commitment_spec=spec
            ),
            reason_refs=("fact-desire",),
        )
        proposed = replace(proposed, commitment_transition_intents=(c,))
    assert OUTPUT_SCHEMA == "executive.candidate.v2"
    raw = proposed.to_dict()
    raw.pop("created_at")
    parsed = parse_candidate(raw, context, created_at=EXEC_NOW)
    with fence_clock(lambda: EXEC_NOW):
        if unknown:
            with pytest.raises(ValueError, match="bounded context"):
                make_authority(context).commit(
                    parsed, context, current=live_state(requirements=()), decision_id="created"
                )
            return
        committed = make_authority(context).commit(
            parsed, context, current=live_state(requirements=()), decision_id="created"
        )
    store.apply(committed)
    publication = (
        store.goal_semantic_publication("goal-spec")
        if kind == "goal"
        else store.commitment_semantic_publication("commitment-spec")
    )
    assert publication is not None and publication.value.semantic_spec == spec
    assert publication.value.modality is (Modality.GOAL if kind == "goal" else Modality.COMMITMENT)
    assert publication.value.source_decision_id == "created"


@pytest.mark.parametrize("field", ["semantic_goal_spec", "semantic_commitment_spec"])
def test_candidate_parser_rejects_missing_and_malformed_create_spec(field: str) -> None:
    from tests.domain.executive.test_executive import candidate_json, snapshot

    transition = (
        goal_transition(G.CREATE, 5)
        if field == "semantic_goal_spec"
        else commitment_transition(C.CREATE, 5)
    )
    key = (
        "goal_transition_intents"
        if field == "semantic_goal_spec"
        else "commitment_transition_intents"
    )
    raw = candidate_json()
    payload = transition.to_dict()
    assert isinstance(payload["payload"], dict)
    spec = payload["payload"][field]
    for corrupt in (None, {}, {"rationale": "untrusted"}, {**spec, "degree": True}):
        payload["payload"][field] = corrupt
        raw[key] = [payload]
        with pytest.raises((ValueError, TypeError)):
            parse_candidate(raw, snapshot(), created_at=NOW)
    del payload["payload"][field]
    with pytest.raises(ValueError):
        parse_candidate(raw, snapshot(), created_at=NOW)


def test_json_boolean_and_number_are_distinct_semantic_content() -> None:
    store = GoalCommitmentStore()
    t = goal_transition(G.CREATE, 0)
    spec = semantic_spec("same")
    t = replace(
        t,
        payload=replace(
            t.payload, semantic_goal_ref="same", semantic_goal_spec=replace(spec, value=True)
        ),
    )
    store.apply(decision("first", 0, goals=(t,)))
    second = goal_transition(G.CREATE, 1, goal_id="other")
    second = replace(
        second,
        payload=replace(
            second.payload, semantic_goal_ref="same", semantic_goal_spec=replace(spec, value=1)
        ),
    )
    before = store.snapshot()
    with pytest.raises(ValueError, match="semantic identity"):
        store.apply(decision("second", 1, goals=(second,)))
    assert store.snapshot() == before
