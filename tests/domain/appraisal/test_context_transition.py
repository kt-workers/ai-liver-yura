"""状態の由来を保持したまま、新しい文脈で評価できることを確認する。"""

from collections.abc import Mapping
from dataclasses import replace
from datetime import timedelta
from typing import Any, cast

import pytest

from app.domain.appraisal import (
    DeepAppraisalContext,
    InternalStateReducer,
    build_deep_request,
    commit_deep_result,
)
from tests.domain.appraisal.test_appraisal_paths import (
    NOW,
    event,
    meaning,
    policy,
    result,
    state,
)


def test_new_context_appraisal_preserves_state_origin_and_commits_new_context() -> None:
    initial = state()
    new_event = replace(event(), revisions=replace(event().revisions, source_context_revision=8))
    new_meaning = replace(meaning(), source_context_revision=8)
    request = build_deep_request(
        new_event,
        new_meaning,
        initial,
        DeepAppraisalContext(),
        request_id="new-context",
        trace_id=new_event.trace_id,
        created_at=NOW,
        policy=policy(),
    )
    assert cast(Mapping[str, Any], request.input.value)["state"]["source_context_revision"] == 7
    candidate = commit_deep_result(
        request,
        result(request),
        event=new_event,
        snapshot=initial,
        context=DeepAppraisalContext(),
        current_source_context_revision=8,
        current_state_revision=initial.revision,
        policy=policy(),
    )
    assert candidate.base_state_revision == initial.revision
    owner = InternalStateReducer(initial)
    committed = owner.commit_with_facts(
        candidate,
        current_source_context_revision=8,
        committed_at=NOW + timedelta(seconds=3),
        facts_revision=1,
    )
    assert committed.internal_state.source_context_revision == 8
    assert committed.appraisal_facts.source_context_revision == 8
    assert initial.source_context_revision == 7


@pytest.mark.parametrize("live_context,live_state", [(9, 3), (8, 4)])
def test_new_context_result_still_rejects_later_changes(live_context: int, live_state: int) -> None:
    new_event = replace(event(), revisions=replace(event().revisions, source_context_revision=8))
    request = build_deep_request(
        new_event,
        None,
        state(),
        DeepAppraisalContext(),
        request_id="stale",
        trace_id=new_event.trace_id,
        created_at=NOW,
        policy=policy(),
    )
    with pytest.raises(ValueError, match="stale"):
        commit_deep_result(
            request,
            result(request),
            event=new_event,
            snapshot=state(),
            context=DeepAppraisalContext(),
            current_source_context_revision=live_context,
            current_state_revision=live_state,
            policy=policy(),
        )


@pytest.mark.parametrize("path", ["deep", "fast", "commit"])
def test_state_context_cannot_regress(path: str) -> None:
    from app.domain.appraisal import appraise_event

    original_event = event()
    newer_state = replace(state(), source_context_revision=8)
    owner = InternalStateReducer(newer_state)
    with pytest.raises(ValueError, match="古い文脈"):
        if path == "deep":
            build_deep_request(
                original_event,
                None,
                newer_state,
                DeepAppraisalContext(),
                request_id="old",
                trace_id=original_event.trace_id,
                created_at=NOW,
                policy=policy(),
            )
        elif path == "fast":
            appraise_event(original_event, newer_state, (), candidate_id="old", created_at=NOW)
        else:
            request = build_deep_request(
                original_event,
                None,
                state(),
                DeepAppraisalContext(),
                request_id="old",
                trace_id=original_event.trace_id,
                created_at=NOW,
                policy=policy(),
            )
            candidate = commit_deep_result(
                request,
                result(request),
                event=original_event,
                snapshot=state(),
                context=DeepAppraisalContext(),
                current_source_context_revision=7,
                current_state_revision=3,
                policy=policy(),
            )
            owner.commit_with_facts(
                candidate,
                current_source_context_revision=7,
                committed_at=NOW + timedelta(seconds=3),
                facts_revision=1,
            )
    assert owner.snapshot() is newer_state
