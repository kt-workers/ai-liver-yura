"""既存Executive搬送容量とCREATEのatomicな保存境界を検証する。"""

import json
from dataclasses import replace

import pytest

from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY as BOUNDS
from app.domain.executive import CommitmentTransitionOperation as C
from app.domain.executive import CommittedExecutiveDecision
from app.domain.executive import GoalTransitionOperation as G
from app.domain.executive.deliberator import validate_candidate_bounds
from app.domain.goals import GoalCommitmentStore
from tests.domain.goals.test_goal_commitment_store import (
    commitment_transition,
    decision,
    goal_transition,
)
from tests.helpers.goal_semantics import semantic_spec

LIMIT = BOUNDS.executive.max_fact_payload_json_bytes


def size(value: object) -> int:
    return len(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    )


def create(kind: str, value: str) -> CommittedExecutiveDecision:
    spec = replace(semantic_spec("semantic"), value=value)
    if kind == "goal":
        t = goal_transition(G.CREATE, 0)
        t = replace(
            t, payload=replace(t.payload, semantic_goal_ref="semantic", semantic_goal_spec=spec)
        )
        return decision("create", 0, goals=(t,))
    c = commitment_transition(C.CREATE, 0)
    c = replace(
        c,
        payload=replace(
            c.payload, semantic_commitment_ref="semantic", semantic_commitment_spec=spec
        ),
    )
    return decision("create", 0, commitments=(c,))


def text_bytes(count: int, unicode: bool) -> str:
    return "あ" * (count // 3) + "x" * (count % 3) if unicode else "x" * count


@pytest.mark.parametrize("kind", ["goal", "commitment"])
@pytest.mark.parametrize("unicode", [False, True])
@pytest.mark.parametrize("extra", [0, 1])
def test_spec_exact_transport_boundary(kind: str, unicode: bool, extra: int) -> None:
    overhead = size(replace(semantic_spec("semantic"), value="").to_dict())
    value = text_bytes(LIMIT - overhead + extra, unicode)
    proposed = create(kind, value)
    assert size(replace(semantic_spec("semantic"), value=value).to_dict()) == LIMIT + extra
    if extra:
        with pytest.raises(ValueError, match="semantic spec transport"):
            validate_candidate_bounds(proposed.candidate, BOUNDS.executive)
    else:
        validate_candidate_bounds(proposed.candidate, BOUNDS.executive)


@pytest.mark.parametrize("kind", ["goal", "commitment"])
@pytest.mark.parametrize("unicode", [False, True])
@pytest.mark.parametrize("extra", [0, 1])
def test_complete_state_exact_transport_boundary(kind: str, unicode: bool, extra: int) -> None:
    sample = GoalCommitmentStore().apply(create(kind, "")).snapshot
    state = (sample.goals + sample.commitments)[0]
    value = text_bytes(LIMIT - size(state.to_dict()) + extra, unicode)
    proposed = create(kind, value)
    # spec単体では収まる候補も、完全Stateの搬送容量を満たす必要がある。
    validate_candidate_bounds(proposed.candidate, BOUNDS.executive)
    store = GoalCommitmentStore(bounds=BOUNDS)
    before = store.snapshot()
    if extra:
        with pytest.raises(ValueError, match="transport"):
            store.apply(proposed)
        assert store.snapshot() == before
        assert store.goal_semantic_publication("goal-1") is None
        assert store.commitment_semantic_publication("commitment-1") is None
    else:
        result = store.apply(proposed).snapshot
        saved = (result.goals + result.commitments)[0]
        assert size(saved.to_dict()) == LIMIT
        restored = GoalCommitmentStore(result, bounds=BOUNDS)
        assert restored.snapshot() == result
        publication = (
            restored.goal_semantic_publication("goal-1")
            if kind == "goal"
            else restored.commitment_semantic_publication("commitment-1")
        )
        assert publication is not None and publication.value.state == saved


def test_oversize_batch_keeps_every_state_and_revision_unchanged() -> None:
    store = GoalCommitmentStore()
    large = create("commitment", "x" * LIMIT)
    batch = decision(
        "batch",
        0,
        goals=(goal_transition(G.CREATE, 0),),
        commitments=large.candidate.commitment_transition_intents,
    )
    before = store.snapshot()
    with pytest.raises(ValueError, match="transport"):
        store.apply(batch)
    assert store.snapshot() == before
    # 非適用batchのdecision/intent IDは消費しない。
    legal = replace(batch, candidate=replace(batch.candidate, commitment_transition_intents=()))
    assert store.apply(legal).snapshot.revision == 1


def test_injected_existing_bound_applies_to_lifecycle_and_restore() -> None:
    small = GoalCommitmentStore().apply(create("goal", "")).snapshot
    initial_size = size(small.goals[0].to_dict())
    bounds = replace(
        BOUNDS, executive=replace(BOUNDS.executive, max_fact_payload_json_bytes=initial_size)
    )
    store = GoalCommitmentStore(small, bounds=bounds)
    # COMPLETEDはPROPOSEDより長いので、合法なACTIVE状態から上限超過を実証する。
    active = store.apply(decision("activate", 1, goals=(goal_transition(G.ACTIVATE, 1),))).snapshot
    with pytest.raises(ValueError, match="transport"):
        store.apply(decision("complete", 2, goals=(goal_transition(G.COMPLETE, 2),)))
    assert store.snapshot() == active
    with pytest.raises(ValueError, match="transport"):
        GoalCommitmentStore(
            small,
            bounds=replace(
                bounds,
                executive=replace(bounds.executive, max_fact_payload_json_bytes=initial_size - 1),
            ),
        )
