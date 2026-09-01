from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import Protocol

from app.domain.contracts.common import require_identifier, require_revision
from app.domain.memory.contracts import (
    MemoryEvidenceView,
    MemoryFreshnessState,
)

CANONICAL_MEMORY_TOKEN_ESTIMATOR_ID = "memory.utf8_bytes_div3.v1"


class MemoryRankingSignal(str, Enum):
    SEMANTIC_RELEVANCE = "semantic_relevance"
    RECENCY = "recency"
    IMPORTANCE = "importance"
    CONFIDENCE = "confidence"
    RELATIONSHIP_RELEVANCE = "relationship_relevance"
    ACTIVITY_TOPIC_RELEVANCE = "activity_topic_relevance"
    MOTIVATION_RELEVANCE = "motivation_relevance"
    FRESHNESS = "freshness"
    CONTRADICTION_CONFIDENCE = "contradiction_confidence"


class MemoryRankingPolarity(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"


class MemoryRankingMissingBehavior(str, Enum):
    ZERO = "zero"
    EXCLUDE = "exclude"
    REJECT_QUERY = "reject_query"


class MemoryStableTieBreaker(str, Enum):
    SCORE_DESC_OBSERVED_AT_DESC_MEMORY_ID_ASC = (
        "score_desc_observed_at_desc_memory_id_asc"
    )


class MemoryRetrievalFailureCode(str, Enum):
    POLICY_MISSING = "memory_retrieval_policy_missing"
    POLICY_STALE = "memory_retrieval_policy_stale"
    REQUIRED_SIGNAL_MISSING = "memory_retrieval_required_signal_missing"
    INVALID_RECORD_TIME = "memory_retrieval_invalid_record_time"
    INVALID_SEMANTIC_SCORE = "memory_retrieval_invalid_semantic_score"


class MemoryRetrievalDiagnosticCode(str, Enum):
    UNRANKABLE_ZERO_DENOMINATOR = "memory_unrankable_zero_denominator"
    INVALID_RECORD_TIME = "memory_invalid_record_time"


class MemoryRetrievalError(ValueError):
    def __init__(self, code: MemoryRetrievalFailureCode, detail: str) -> None:
        super().__init__(f"{code.value}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class MemoryRankingSignalRule:
    signal: MemoryRankingSignal
    weight: float
    polarity: MemoryRankingPolarity
    missing_behavior: MemoryRankingMissingBehavior

    def __post_init__(self) -> None:
        if not isinstance(self.signal, MemoryRankingSignal):
            raise ValueError("memory ranking signal が不正です")
        if type(self.weight) not in (int, float) or not isfinite(self.weight) or self.weight < 0:
            raise ValueError("memory ranking weight は有限の0以上でなければなりません")
        if not isinstance(self.polarity, MemoryRankingPolarity):
            raise ValueError("memory ranking polarity が不正です")
        if not isinstance(self.missing_behavior, MemoryRankingMissingBehavior):
            raise ValueError("memory ranking missing behavior が不正です")
        object.__setattr__(self, "weight", float(self.weight))


@dataclass(frozen=True, slots=True)
class MemoryFreshnessScoreRule:
    freshness: MemoryFreshnessState
    score: float

    def __post_init__(self) -> None:
        if not isinstance(self.freshness, MemoryFreshnessState):
            raise ValueError("memory freshness state が不正です")
        if (
            type(self.score) not in (int, float)
            or not isfinite(self.score)
            or not 0 <= self.score <= 1
        ):
            raise ValueError("memory freshness score は[0,1]でなければなりません")
        object.__setattr__(self, "score", float(self.score))


@dataclass(frozen=True, slots=True)
class MemoryRetrievalRankingPolicy:
    policy_id: str
    policy_revision: int
    signal_rules: tuple[MemoryRankingSignalRule, ...]
    recency_half_life_seconds: float
    stable_tie_breaker: MemoryStableTieBreaker
    token_estimator_id: str
    token_estimator_revision: int
    freshness_scores: tuple[MemoryFreshnessScoreRule, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.policy_id, "memory retrieval policy_id")
        require_revision(self.policy_revision, "memory retrieval policy_revision")
        rules = tuple(self.signal_rules)
        if not rules or any(not isinstance(rule, MemoryRankingSignalRule) for rule in rules):
            raise ValueError("memory ranking signal_rules が不正です")
        signals = tuple(rule.signal for rule in rules)
        if len(signals) != len(set(signals)):
            raise ValueError("memory ranking signalは重複できません")
        if not any(rule.weight > 0 for rule in rules):
            raise ValueError("memory ranking policyにはpositive weightが必要です")
        half_life = self.recency_half_life_seconds
        if type(half_life) not in (int, float) or not isfinite(half_life) or half_life <= 0:
            raise ValueError("recency_half_life_seconds は有限の正数でなければなりません")
        if not isinstance(self.stable_tie_breaker, MemoryStableTieBreaker):
            raise ValueError("memory stable tie breaker が不正です")
        require_identifier(self.token_estimator_id, "memory token_estimator_id")
        require_revision(self.token_estimator_revision, "memory token_estimator_revision")
        if self.token_estimator_id != CANONICAL_MEMORY_TOKEN_ESTIMATOR_ID:
            raise ValueError("未対応のmemory token estimatorです")
        scores = tuple(self.freshness_scores)
        if any(not isinstance(rule, MemoryFreshnessScoreRule) for rule in scores):
            raise ValueError("memory freshness score map が不正です")
        states = tuple(rule.freshness for rule in scores)
        if len(states) != len(set(states)):
            raise ValueError("memory freshness score stateは重複できません")
        if MemoryRankingSignal.FRESHNESS in signals and set(states) != set(MemoryFreshnessState):
            raise ValueError("FRESHNESS rankingには全freshness stateのscore mapが必要です")
        object.__setattr__(self, "signal_rules", rules)
        object.__setattr__(self, "recency_half_life_seconds", float(half_life))
        object.__setattr__(self, "freshness_scores", scores)

    def same_generation(self, policy_id: str, policy_revision: int) -> bool:
        return self.policy_id == policy_id and self.policy_revision == policy_revision

    def freshness_score(self, state: MemoryFreshnessState) -> float | None:
        for rule in self.freshness_scores:
            if rule.freshness is state:
                return rule.score
        return None


class MemoryRetrievalRankingPolicyPort(Protocol):
    def current_memory_retrieval_policy(self) -> MemoryRetrievalRankingPolicy: ...


@dataclass(frozen=True, slots=True)
class MemorySemanticRelevance:
    memory_id: str
    score: float

    def __post_init__(self) -> None:
        require_identifier(self.memory_id, "memory semantic relevance memory_id")
        if (
            type(self.score) not in (int, float)
            or not isfinite(self.score)
            or not 0 <= self.score <= 1
        ):
            raise ValueError("memory semantic relevance score は[0,1]でなければなりません")
        object.__setattr__(self, "score", float(self.score))


@dataclass(frozen=True, slots=True)
class MemoryRetrievalDiagnostic:
    code: MemoryRetrievalDiagnosticCode
    memory_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.code, MemoryRetrievalDiagnosticCode):
            raise ValueError("memory retrieval diagnostic code が不正です")
        require_identifier(self.memory_id, "memory retrieval diagnostic memory_id")


@dataclass(frozen=True, slots=True)
class RankedMemoryEvidenceView(MemoryEvidenceView):
    ranking_policy_id: str = ""
    ranking_policy_revision: int = 0
    token_estimator_id: str = ""
    token_estimator_revision: int = 0
    diagnostics: tuple[MemoryRetrievalDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        MemoryEvidenceView.__post_init__(self)
        require_identifier(self.ranking_policy_id, "memory ranking_policy_id")
        require_revision(self.ranking_policy_revision, "memory ranking_policy_revision")
        require_identifier(self.token_estimator_id, "memory token_estimator_id")
        require_revision(self.token_estimator_revision, "memory token_estimator_revision")
        diagnostics = tuple(self.diagnostics)
        if any(not isinstance(item, MemoryRetrievalDiagnostic) for item in diagnostics):
            raise ValueError("memory retrieval diagnostics が不正です")
        object.__setattr__(self, "diagnostics", diagnostics)
