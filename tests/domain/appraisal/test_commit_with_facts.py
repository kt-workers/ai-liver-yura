"""状態と評価事実の同時確定、失敗時の非更新、実行判断への接続を検証する。"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta

import pytest

from app.domain.appraisal import AppraisalCandidate, AppraisalStateCommit, InternalStateReducer
from app.domain.executive import (
    CommittedExecutiveDecision,
    ExecutiveOutcome,
    build_request,
    commit_result,
)
from tests.domain.appraisal.test_state_reducer import NOW, candidate, facet, proposal, snapshot
from tests.domain.executive import test_executive as executive
from tests.helpers.executive_requirements import make_authority

COMMITTED_AT = NOW + timedelta(seconds=2)


def commit(owner: InternalStateReducer, item: AppraisalCandidate) -> AppraisalStateCommit:
    return owner.commit_with_facts(
        item, current_source_context_revision=7, committed_at=COMMITTED_AT, facts_revision=9
    )


def test_state_and_facts_reach_executive_without_changing_candidate_origin() -> None:
    original = candidate(proposal())
    owner = InternalStateReducer(snapshot(facet()))
    result = commit(owner, original)
    assert result.candidate is original
    assert original.base_state_revision == 3
    assert result.internal_state is owner.snapshot()
    assert result.internal_state.revision == result.appraisal_facts.internal_state_revision == 4
    assert result.appraisal_facts.revision == 9
    assert result.appraisal_facts.salience == original.salience
    assert result.appraisal_facts.evidence_refs == original.evidence_refs
    context = replace(
        executive.snapshot(),
        internal_state=result.internal_state,
        appraisal_facts=result.appraisal_facts,
        captured_at=COMMITTED_AT,
    )
    assert context.to_dict()["appraisal_facts"] == result.appraisal_facts.to_dict()
    later = owner.commit(
        replace(original, candidate_id="later", base_state_revision=4, created_at=COMMITTED_AT),
        current_source_context_revision=7,
        committed_at=COMMITTED_AT,
    )
    with pytest.raises(ValueError, match="state revision"):
        replace(context, internal_state=later)


@pytest.mark.parametrize("facts_revision", [-1, True])
def test_invalid_facts_revision_does_not_commit_state(facts_revision: int) -> None:
    before = snapshot(facet())
    owner = InternalStateReducer(before)
    with pytest.raises(ValueError):
        owner.commit_with_facts(
            candidate(proposal()),
            current_source_context_revision=7,
            committed_at=COMMITTED_AT,
            facts_revision=facts_revision,
        )
    assert owner.snapshot() is before


def test_unbounded_facts_do_not_leave_state_partially_committed() -> None:
    before = snapshot(facet())
    owner = InternalStateReducer(before)
    item = replace(candidate(proposal()), evidence_refs=tuple(f"e:{i}" for i in range(17)))
    with pytest.raises(ValueError, match="bounded maximum"):
        commit(owner, item)
    assert owner.snapshot() is before
    assert commit(owner, candidate(proposal())).internal_state.revision == 4


@pytest.mark.parametrize(
    "item",
    [
        candidate(proposal(), base=2),
        candidate(proposal(), context=8),
        candidate(proposal(delta=0.9)),
        candidate(),
        replace(candidate(proposal()), created_at=NOW - timedelta(seconds=1)),
    ],
)
def test_original_reducer_rejections_remain_atomic(item: AppraisalCandidate) -> None:
    before = snapshot(facet())
    owner = InternalStateReducer(before)
    with pytest.raises(ValueError):
        commit(owner, item)
    assert owner.snapshot() is before


def test_new_source_context_uses_actual_updated_state_context() -> None:
    owner = InternalStateReducer(snapshot(facet()))
    item = candidate(proposal(), context=8)
    result = owner.commit_with_facts(
        item, current_source_context_revision=8, committed_at=COMMITTED_AT, facts_revision=10
    )
    assert result.internal_state.source_context_revision == 8
    assert result.appraisal_facts.source_context_revision == 8
    assert item.base_state_revision == 3


def test_competing_candidates_only_commit_one_pair() -> None:
    owner = InternalStateReducer(snapshot(facet()))

    def invoke(index: int) -> AppraisalStateCommit | None:
        try:
            return commit(owner, replace(candidate(proposal()), candidate_id=f"c:{index}"))
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(invoke, range(2)))
    accepted = [item for item in results if item is not None]
    assert len(accepted) == 1
    assert owner.snapshot() is accepted[0].internal_state
    assert owner.snapshot().revision == 4


@pytest.mark.parametrize("changed", [None, "state", "facts"])
def test_executive_request_and_commit_keep_both_freshness_checks(changed: str | None) -> None:
    result = commit(InternalStateReducer(snapshot(facet())), candidate(proposal()))
    context = replace(
        executive.snapshot(),
        internal_state=result.internal_state,
        appraisal_facts=result.appraisal_facts,
        captured_at=COMMITTED_AT,
    )
    policy = executive.policy()
    request = build_request(
        context,
        request_id="request-pair",
        trace_id="trace-pair",
        created_at=COMMITTED_AT,
        policy=policy,
    )
    response = replace(
        executive.success(request),
        started_at=COMMITTED_AT,
        completed_at=COMMITTED_AT + timedelta(seconds=1),
    )
    current = executive.live_state(
        internal_state_revision=4 + (changed == "state"),
        appraisal_facts_revision=9 + (changed == "facts"),
    )

    def decide() -> CommittedExecutiveDecision:
        return commit_result(
            request,
            response,
            snapshot=context,
            current=current,
            authority=make_authority(),
            decision_id="decision-pair",
            committed_at=COMMITTED_AT + timedelta(seconds=2),
            policy=policy,
        )

    if changed is None:
        assert decide().candidate.outcome is ExecutiveOutcome.RESPOND
    else:
        with pytest.raises(ValueError):
            decide()
