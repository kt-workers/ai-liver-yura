"""Structural settings contracts owned by Streaming Subsystem application."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol


class CommentModerationSettings(Protocol):
    blocked_terms: tuple[str, ...]
    allowed_terms: tuple[str, ...]
    max_comment_length: int
    repeated_message_window_seconds: int
    repeated_message_limit: int
    url_policy: str
    unknown_message_type_policy: str
    max_concurrent_evaluations: int
    evaluation_queue_capacity: int
    timeout_seconds: float


class CommentRankingSettings(Protocol):
    weights: Mapping[str, float]
    selection_threshold: float
    minimum_conversation_fit: float
    candidate_ttl_seconds: int
    reservation_ttl_seconds: int
    max_pool_size: int
    max_rank_batch_size: int
    history_size: int
    author_cooldown_count: int
    semantic_timeout_seconds: float
    max_concurrent_rankings: int
    queue_capacity: int


class CommentResponseSettings(Protocol):
    max_characters: int
    max_sentences: int
    allow_follow_up_question: bool
    mention_author_name: str
    repeat_comment_text: bool
    response_cooldown_seconds: int
    max_retries: int


@dataclass(frozen=True, slots=True)
class DefaultCommentModerationSettings:
    blocked_terms: tuple[str, ...] = ()
    allowed_terms: tuple[str, ...] = ()
    max_comment_length: int = 300
    repeated_message_window_seconds: int = 30
    repeated_message_limit: int = 3
    url_policy: str = "review"
    unknown_message_type_policy: str = "ignore"
    max_concurrent_evaluations: int = 4
    evaluation_queue_capacity: int = 128
    timeout_seconds: float = 3.0


def _ranking_weights() -> Mapping[str, float]:
    return {
        "recency": 0.15,
        "relevance": 0.25,
        "novelty": 0.15,
        "conversation_fit": 0.20,
        "engagement": 0.15,
        "fairness": 0.10,
    }


@dataclass(frozen=True, slots=True)
class DefaultCommentRankingSettings:
    weights: Mapping[str, float] = field(default_factory=_ranking_weights)
    selection_threshold: float = 0.55
    minimum_conversation_fit: float = 0.5
    candidate_ttl_seconds: int = 90
    reservation_ttl_seconds: int = 30
    max_pool_size: int = 200
    max_rank_batch_size: int = 50
    history_size: int = 100
    author_cooldown_count: int = 2
    semantic_timeout_seconds: float = 2.0
    max_concurrent_rankings: int = 1
    queue_capacity: int = 16


@dataclass(frozen=True, slots=True)
class DefaultCommentResponseSettings:
    max_characters: int = 140
    max_sentences: int = 3
    allow_follow_up_question: bool = True
    mention_author_name: str = "optional"
    repeat_comment_text: bool = False
    response_cooldown_seconds: int = 5
    max_retries: int = 2
