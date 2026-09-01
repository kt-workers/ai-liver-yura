from __future__ import annotations

from app.domain.memory import (
    CANONICAL_MEMORY_TOKEN_ESTIMATOR_ID,
    MemoryFreshnessScoreRule,
    MemoryFreshnessState,
    MemoryRankingMissingBehavior,
    MemoryRankingPolarity,
    MemoryRankingSignal,
    MemoryRankingSignalRule,
    MemoryRetrievalRankingPolicy,
    MemoryStableTieBreaker,
)


def retrieval_policy(
    *,
    revision: int = 1,
    rules: tuple[MemoryRankingSignalRule, ...] | None = None,
    half_life_seconds: float = 3600.0,
) -> MemoryRetrievalRankingPolicy:
    signal_rules = rules or (
        MemoryRankingSignalRule(
            MemoryRankingSignal.CONFIDENCE,
            0.5,
            MemoryRankingPolarity.POSITIVE,
            MemoryRankingMissingBehavior.ZERO,
        ),
        MemoryRankingSignalRule(
            MemoryRankingSignal.FRESHNESS,
            0.2,
            MemoryRankingPolarity.POSITIVE,
            MemoryRankingMissingBehavior.ZERO,
        ),
        MemoryRankingSignalRule(
            MemoryRankingSignal.SEMANTIC_RELEVANCE,
            0.3,
            MemoryRankingPolarity.POSITIVE,
            MemoryRankingMissingBehavior.ZERO,
        ),
    )
    freshness_scores = (
        MemoryFreshnessScoreRule(MemoryFreshnessState.FRESH, 1.0),
        MemoryFreshnessScoreRule(MemoryFreshnessState.STALE, 0.5),
        MemoryFreshnessScoreRule(MemoryFreshnessState.HISTORICAL, 0.0),
    )
    return MemoryRetrievalRankingPolicy(
        policy_id="test.memory-retrieval",
        policy_revision=revision,
        signal_rules=signal_rules,
        recency_half_life_seconds=half_life_seconds,
        stable_tie_breaker=(
            MemoryStableTieBreaker.SCORE_DESC_OBSERVED_AT_DESC_MEMORY_ID_ASC
        ),
        token_estimator_id=CANONICAL_MEMORY_TOKEN_ESTIMATOR_ID,
        token_estimator_revision=1,
        freshness_scores=(
            freshness_scores
            if any(rule.signal is MemoryRankingSignal.FRESHNESS for rule in signal_rules)
            else ()
        ),
    )
