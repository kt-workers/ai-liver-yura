from __future__ import annotations

from datetime import datetime, timedelta, timezone
from json import dumps
from math import inf, nan

import pytest

from app.domain.memory import (
    CANONICAL_MEMORY_TOKEN_ESTIMATOR_ID,
    InMemoryMemoryRepository,
    MemoryConfidence,
    MemoryContent,
    MemoryFreshnessScoreRule,
    MemoryFreshnessState,
    MemoryKind,
    MemoryProvenance,
    MemoryRankingMissingBehavior,
    MemoryRankingPolarity,
    MemoryRankingSignal,
    MemoryRankingSignalRule,
    MemoryRetrievalDiagnosticCode,
    MemoryRetrievalError,
    MemoryRetrievalFailureCode,
    MemoryRetrievalQuery,
    MemoryRetrievalRankingPolicy,
    MemorySemanticRelevance,
    MemorySourceKind,
    MemoryStableTieBreaker,
    MemoryStoreAuthority,
    MemoryTemporalState,
    MemoryWriteRequest,
    ValidatedMemoryCandidate,
)
from tests.domain.memory.policy_fixtures import retrieval_policy

NOW = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)


def rule(
    signal: MemoryRankingSignal,
    *,
    weight: float = 1.0,
    polarity: MemoryRankingPolarity = MemoryRankingPolarity.POSITIVE,
    missing: MemoryRankingMissingBehavior = MemoryRankingMissingBehavior.ZERO,
) -> MemoryRankingSignalRule:
    return MemoryRankingSignalRule(signal, weight, polarity, missing)


def policy(
    *rules: MemoryRankingSignalRule,
    revision: int = 1,
    half_life: float = 60.0,
) -> MemoryRetrievalRankingPolicy:
    freshness_scores = (
        MemoryFreshnessScoreRule(MemoryFreshnessState.FRESH, 1.0),
        MemoryFreshnessScoreRule(MemoryFreshnessState.STALE, 0.5),
        MemoryFreshnessScoreRule(MemoryFreshnessState.HISTORICAL, 0.0),
    )
    return MemoryRetrievalRankingPolicy(
        "test.memory.d10",
        revision,
        tuple(rules) or (rule(MemoryRankingSignal.CONFIDENCE),),
        half_life,
        MemoryStableTieBreaker.SCORE_DESC_OBSERVED_AT_DESC_MEMORY_ID_ASC,
        CANONICAL_MEMORY_TOKEN_ESTIMATOR_ID,
        1,
        freshness_scores=(
            freshness_scores
            if any(item.signal is MemoryRankingSignal.FRESHNESS for item in rules)
            else ()
        ),
    )


def memory_candidate(
    memory_id: str,
    *,
    confidence: float = 0.8,
    observed_at: datetime = NOW,
    value: object = "value",
) -> ValidatedMemoryCandidate:
    return ValidatedMemoryCandidate(
        memory_id,
        MemoryKind.SEMANTIC,
        MemoryContent("fact", value),
        MemoryProvenance(
            MemorySourceKind.TYPED_FACT,
            (),
            (f"fact:{memory_id}",),
            None,
            observed_at,
            observed_at,
        ),
        MemoryConfidence(confidence, "test"),
        MemoryTemporalState(MemoryFreshnessState.FRESH, observed_at=observed_at),
        observed_at,
    )


def retrieval_query(
    *,
    created_at: datetime = NOW,
    max_items: int = 32,
    max_tokens: int = 100_000,
    semantic_query: str | None = None,
) -> MemoryRetrievalQuery:
    return MemoryRetrievalQuery(
        "query:d10",
        "test",
        "d10",
        created_at,
        max_items=max_items,
        max_estimated_tokens=max_tokens,
        semantic_query=semantic_query,
    )


def store_with_policy(
    ranking_policy: MemoryRetrievalRankingPolicy,
) -> tuple[MemoryStoreAuthority, InMemoryMemoryRepository]:
    repository = InMemoryMemoryRepository()
    return MemoryStoreAuthority(repository, ranking_policy=ranking_policy), repository


@pytest.mark.parametrize("invalid", [True, nan, inf, -inf, -0.1])
def test_ranking_weight_rejects_invalid_numeric_values(invalid: object) -> None:
    with pytest.raises(ValueError):
        MemoryRankingSignalRule(
            MemoryRankingSignal.CONFIDENCE,
            invalid,  # type: ignore[arg-type]
            MemoryRankingPolarity.POSITIVE,
            MemoryRankingMissingBehavior.ZERO,
        )


@pytest.mark.parametrize("invalid", [True, nan, inf, -inf, 0.0, -1.0])
def test_recency_half_life_rejects_invalid_numeric_values(invalid: object) -> None:
    with pytest.raises(ValueError):
        policy(rule(MemoryRankingSignal.CONFIDENCE), half_life=invalid)  # type: ignore[arg-type]


def test_policy_rejects_duplicate_signals_and_all_zero_weights() -> None:
    with pytest.raises(ValueError, match="重複"):
        policy(
            rule(MemoryRankingSignal.CONFIDENCE),
            rule(MemoryRankingSignal.CONFIDENCE),
        )
    with pytest.raises(ValueError, match="positive weight"):
        policy(rule(MemoryRankingSignal.CONFIDENCE, weight=0.0))


def test_freshness_signal_requires_exact_score_map() -> None:
    with pytest.raises(ValueError, match="全freshness"):
        MemoryRetrievalRankingPolicy(
            "test.memory.d10",
            1,
            (rule(MemoryRankingSignal.FRESHNESS),),
            60.0,
            MemoryStableTieBreaker.SCORE_DESC_OBSERVED_AT_DESC_MEMORY_ID_ASC,
            CANONICAL_MEMORY_TOKEN_ESTIMATOR_ID,
            1,
            freshness_scores=(
                MemoryFreshnessScoreRule(MemoryFreshnessState.FRESH, 1.0),
            ),
        )


def test_recency_half_life_is_point_five_and_two_half_lives_is_point_two_five() -> None:
    ranking_policy = policy(rule(MemoryRankingSignal.RECENCY), half_life=60.0)
    store, _ = store_with_policy(ranking_policy)
    store.write(
        MemoryWriteRequest(memory_candidate("memory:half", observed_at=NOW - timedelta(seconds=60)))
    )
    store.write(
        MemoryWriteRequest(memory_candidate("memory:two", observed_at=NOW - timedelta(seconds=120)))
    )
    view = store.retrieve(retrieval_query())
    scores = {item.memory_id: item.score for item in view.items}
    assert scores["memory:half"] == pytest.approx(0.5)
    assert scores["memory:two"] == pytest.approx(0.25)


def test_future_reference_time_is_excluded_with_typed_diagnostic() -> None:
    store, _ = store_with_policy(policy(rule(MemoryRankingSignal.RECENCY)))
    store.write(
        MemoryWriteRequest(memory_candidate("memory:future", observed_at=NOW + timedelta(seconds=1)))
    )
    view = store.retrieve(retrieval_query())
    assert view.items == ()
    assert view.diagnostics[0].code is MemoryRetrievalDiagnosticCode.INVALID_RECORD_TIME
    assert view.diagnostics[0].memory_id == "memory:future"


def test_positive_and_negative_polarity_use_closed_formula() -> None:
    positive, _ = store_with_policy(
        policy(rule(MemoryRankingSignal.CONFIDENCE, polarity=MemoryRankingPolarity.POSITIVE))
    )
    positive.write(MemoryWriteRequest(memory_candidate("memory:positive", confidence=0.8)))
    assert positive.retrieve(retrieval_query()).items[0].score == pytest.approx(0.8)

    negative, _ = store_with_policy(
        policy(rule(MemoryRankingSignal.CONFIDENCE, polarity=MemoryRankingPolarity.NEGATIVE))
    )
    negative.write(MemoryWriteRequest(memory_candidate("memory:negative", confidence=0.8)))
    assert negative.retrieve(retrieval_query()).items[0].score == pytest.approx(0.2)


def test_missing_zero_exclude_and_reject_query_are_distinct() -> None:
    zero_policy = policy(
        rule(MemoryRankingSignal.CONFIDENCE),
        rule(MemoryRankingSignal.IMPORTANCE, missing=MemoryRankingMissingBehavior.ZERO),
    )
    zero, _ = store_with_policy(zero_policy)
    zero.write(MemoryWriteRequest(memory_candidate("memory:zero", confidence=0.8)))
    assert zero.retrieve(retrieval_query()).items[0].score == pytest.approx(0.4)

    exclude_policy = policy(
        rule(MemoryRankingSignal.CONFIDENCE),
        rule(MemoryRankingSignal.IMPORTANCE, missing=MemoryRankingMissingBehavior.EXCLUDE),
    )
    exclude, _ = store_with_policy(exclude_policy)
    exclude.write(MemoryWriteRequest(memory_candidate("memory:exclude", confidence=0.8)))
    assert exclude.retrieve(retrieval_query()).items[0].score == pytest.approx(0.8)

    reject_policy = policy(
        rule(MemoryRankingSignal.CONFIDENCE),
        rule(
            MemoryRankingSignal.IMPORTANCE,
            missing=MemoryRankingMissingBehavior.REJECT_QUERY,
        ),
    )
    reject, _ = store_with_policy(reject_policy)
    reject.write(MemoryWriteRequest(memory_candidate("memory:reject", confidence=0.8)))
    with pytest.raises(MemoryRetrievalError) as exc_info:
        reject.retrieve(retrieval_query())
    assert exc_info.value.code is MemoryRetrievalFailureCode.REQUIRED_SIGNAL_MISSING


def test_zero_denominator_excludes_item_with_diagnostic() -> None:
    ranking_policy = policy(
        rule(
            MemoryRankingSignal.IMPORTANCE,
            missing=MemoryRankingMissingBehavior.EXCLUDE,
        )
    )
    store, _ = store_with_policy(ranking_policy)
    store.write(MemoryWriteRequest(memory_candidate("memory:unrankable")))
    view = store.retrieve(retrieval_query())
    assert view.items == ()
    assert view.diagnostics[0].code is (
        MemoryRetrievalDiagnosticCode.UNRANKABLE_ZERO_DENOMINATOR
    )


def test_tie_break_is_score_then_reference_time_then_memory_id() -> None:
    store, _ = store_with_policy(policy(rule(MemoryRankingSignal.CONFIDENCE)))
    store.write(
        MemoryWriteRequest(
            memory_candidate("memory:old", observed_at=NOW - timedelta(seconds=1))
        )
    )
    store.write(MemoryWriteRequest(memory_candidate("memory:b", observed_at=NOW)))
    store.write(MemoryWriteRequest(memory_candidate("memory:a", observed_at=NOW)))
    assert [item.memory_id for item in store.retrieve(retrieval_query()).items] == [
        "memory:a",
        "memory:b",
        "memory:old",
    ]


def test_utf8_bytes_div3_estimator_is_deterministic_for_ascii_japanese_and_structure() -> None:
    payloads = (
        {"text": "abc"},
        {"text": "ゆら"},
        {"nested": ["ゆら", {"value": 3}]},
    )
    for payload in payloads:
        raw = dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        expected = max(1, (len(raw) + 2) // 3)
        assert MemoryStoreAuthority._estimate_tokens(payload) == expected


def test_item_budget_uses_ranked_prefix_and_marks_truncated() -> None:
    store, _ = store_with_policy(policy(rule(MemoryRankingSignal.CONFIDENCE)))
    for memory_id, confidence in (
        ("memory:first", 0.9),
        ("memory:second", 0.8),
        ("memory:third", 0.7),
    ):
        store.write(MemoryWriteRequest(memory_candidate(memory_id, confidence=confidence)))
    assert len(store.retrieve(retrieval_query(max_items=3)).items) == 3
    exact = store.retrieve(retrieval_query(max_items=2))
    assert [item.memory_id for item in exact.items] == ["memory:first", "memory:second"]
    assert exact.truncated


def test_token_budget_stops_at_first_overflow_without_later_small_item_backfill() -> None:
    store, _ = store_with_policy(policy(rule(MemoryRankingSignal.CONFIDENCE)))
    store.write(
        MemoryWriteRequest(memory_candidate("memory:first", confidence=0.9, value="small"))
    )
    store.write(
        MemoryWriteRequest(
            memory_candidate("memory:second", confidence=0.8, value="x" * 600)
        )
    )
    store.write(
        MemoryWriteRequest(memory_candidate("memory:third", confidence=0.7, value="tiny"))
    )
    full = store.retrieve(retrieval_query())
    first = full.items[0]
    ranking_policy = store.retrieval_ranking_policy
    assert ranking_policy is not None
    envelope_tokens = MemoryStoreAuthority._estimate_tokens(
        {
            "query_id": "query:d10",
            "generated_at": NOW.isoformat(),
            "ranking_policy_id": ranking_policy.policy_id,
            "ranking_policy_revision": ranking_policy.policy_revision,
            "token_estimator_id": ranking_policy.token_estimator_id,
            "token_estimator_revision": ranking_policy.token_estimator_revision,
            "degradation_reasons": [],
            "diagnostics": [],
        }
    )
    view = store.retrieve(
        retrieval_query(max_tokens=envelope_tokens + first.estimated_tokens)
    )
    assert [item.memory_id for item in view.items] == ["memory:first"]
    assert view.truncated


class BrokenIndex:
    def upsert(self, record: object) -> None:
        pass

    def related_scores(
        self, query: str, *, limit: int
    ) -> tuple[MemorySemanticRelevance, ...]:
        raise RuntimeError("index unavailable")


def test_semantic_index_unavailable_degrades_when_missing_policy_allows_it() -> None:
    repository = InMemoryMemoryRepository()
    ranking_policy = policy(
        rule(
            MemoryRankingSignal.SEMANTIC_RELEVANCE,
            missing=MemoryRankingMissingBehavior.ZERO,
        ),
        rule(MemoryRankingSignal.CONFIDENCE),
    )
    store = MemoryStoreAuthority(
        repository,
        BrokenIndex(),
        ranking_policy=ranking_policy,
    )
    store.write(MemoryWriteRequest(memory_candidate("memory:1")))
    view = store.retrieve(retrieval_query(semantic_query="query"))
    assert view.items
    assert view.degraded


def test_semantic_index_unavailable_fails_closed_when_signal_is_required() -> None:
    repository = InMemoryMemoryRepository()
    ranking_policy = policy(
        rule(
            MemoryRankingSignal.SEMANTIC_RELEVANCE,
            missing=MemoryRankingMissingBehavior.REJECT_QUERY,
        )
    )
    store = MemoryStoreAuthority(
        repository,
        BrokenIndex(),
        ranking_policy=ranking_policy,
    )
    store.write(MemoryWriteRequest(memory_candidate("memory:1")))
    with pytest.raises(MemoryRetrievalError) as exc_info:
        store.retrieve(retrieval_query(semantic_query="query"))
    assert exc_info.value.code is MemoryRetrievalFailureCode.REQUIRED_SIGNAL_MISSING


def test_result_carries_ranking_and_token_estimator_provenance() -> None:
    ranking_policy = retrieval_policy(revision=7)
    store, _ = store_with_policy(ranking_policy)
    store.write(MemoryWriteRequest(memory_candidate("memory:1")))
    view = store.retrieve(retrieval_query())
    assert view.ranking_policy_id == ranking_policy.policy_id
    assert view.ranking_policy_revision == 7
    assert view.token_estimator_id == CANONICAL_MEMORY_TOKEN_ESTIMATOR_ID
    assert view.token_estimator_revision == 1


def test_policy_generation_change_during_index_lookup_rejects_old_result() -> None:
    class MutatingIndex:
        def __init__(self) -> None:
            self.store: MemoryStoreAuthority | None = None

        def upsert(self, record: object) -> None:
            pass

        def related_scores(
            self, query: str, *, limit: int
        ) -> tuple[MemorySemanticRelevance, ...]:
            assert self.store is not None
            self.store.update_retrieval_ranking_policy(retrieval_policy(revision=2))
            return (MemorySemanticRelevance("memory:1", 1.0),)

    repository = InMemoryMemoryRepository()
    index = MutatingIndex()
    store = MemoryStoreAuthority(
        repository,
        index,
        ranking_policy=retrieval_policy(revision=1),
    )
    index.store = store
    store.write(MemoryWriteRequest(memory_candidate("memory:1")))
    with pytest.raises(MemoryRetrievalError) as exc_info:
        store.retrieve(retrieval_query(semantic_query="query"))
    assert exc_info.value.code is MemoryRetrievalFailureCode.POLICY_STALE


def test_retrieval_without_policy_fails_closed_instead_of_using_hidden_weights() -> None:
    store = MemoryStoreAuthority(InMemoryMemoryRepository())
    with pytest.raises(MemoryRetrievalError) as exc_info:
        store.retrieve(retrieval_query())
    assert exc_info.value.code is MemoryRetrievalFailureCode.POLICY_MISSING
