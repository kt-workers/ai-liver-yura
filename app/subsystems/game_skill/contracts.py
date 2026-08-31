from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite

from app.domain.contracts.common import (
    JsonValue,
    freeze_json,
    require_aware,
    require_identifier,
    require_revision,
)
from app.domain.llm import LLMInterruptibility, LLMPriority


class GameSessionLifecycle(str, Enum):
    REQUESTED = "requested"
    ADMITTED = "admitted"
    INITIALIZING = "initializing"
    ACTIVE = "active"
    PAUSED = "paused"
    ENDING = "ending"
    ENDED = "ended"
    FAILED = "failed"
    CANCELLED = "cancelled"


class GameActionEffectState(str, Enum):
    NOT_APPLIED = "not_applied"
    APPLIED = "applied"
    AMBIGUOUS = "ambiguous"
    FAILED = "failed"


class GameActionExecutionStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    STALE = "stale"
    UNKNOWN_EFFECT = "unknown_effect"


class GameObservationCategory(str, Enum):
    SESSION_STATE_CHANGE = "session_state_change"
    SCORE_OR_RESULT_MILESTONE = "score_or_result_milestone"
    OPPONENT_SIGNIFICANT_ACTION = "opponent_significant_action"
    DANGER_OR_OPPORTUNITY = "danger_or_opportunity"
    OBJECTIVE_CHANGE = "objective_change"
    MATCH_COMPLETED = "match_completed"


def _refs(values: tuple[str, ...], name: str, *, nonempty: bool = False) -> tuple[str, ...]:
    if not isinstance(values, tuple) or any(
        not isinstance(value, str) or not value.strip() for value in values
    ):
        raise ValueError(f"{name} が不正です")
    if nonempty and not values or len(set(values)) != len(values):
        raise ValueError(f"{name} が不正です")
    return values


@dataclass(frozen=True, slots=True)
class GameSessionIntent:
    session_request_id: str
    decision_id: str
    activity_id: str
    game_capability_id: str
    participant_refs: tuple[str, ...]
    goal_id: str
    goal_revision: int
    strategy_revision: int
    high_level_goal_ref: str
    high_level_strategy: JsonValue
    source_context_revision: int
    priority: LLMPriority
    interruptibility: LLMInterruptibility
    created_at: datetime
    stream_context_ref: str | None = None

    def __post_init__(self) -> None:
        for field in (
            "session_request_id",
            "decision_id",
            "activity_id",
            "game_capability_id",
            "goal_id",
            "high_level_goal_ref",
        ):
            require_identifier(getattr(self, field), field)
        object.__setattr__(
            self,
            "participant_refs",
            _refs(self.participant_refs, "participant_refs", nonempty=True),
        )
        for field in ("goal_revision", "strategy_revision", "source_context_revision"):
            require_revision(getattr(self, field), field)
        if not isinstance(self.priority, LLMPriority) or not isinstance(
            self.interruptibility, LLMInterruptibility
        ):
            raise ValueError("session priority が不正です")
        if self.stream_context_ref is not None:
            require_identifier(self.stream_context_ref, "stream_context_ref")
        object.__setattr__(self, "high_level_strategy", freeze_json(self.high_level_strategy))
        require_aware(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class GameStrategyUpdate:
    update_id: str
    session_id: str
    goal_id: str
    expected_goal_revision: int
    strategy_revision: int
    strategy_payload: JsonValue
    source_decision_id: str
    created_at: datetime

    def __post_init__(self) -> None:
        for field in ("update_id", "session_id", "goal_id", "source_decision_id"):
            require_identifier(getattr(self, field), field)
        require_revision(self.expected_goal_revision, "expected_goal_revision")
        require_revision(self.strategy_revision, "strategy_revision")
        object.__setattr__(self, "strategy_payload", freeze_json(self.strategy_payload))
        require_aware(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class GameFrameAction:
    action_id: str
    session_id: str
    game_state_revision: int
    strategy_revision: int
    action_kind: str
    parameters: Mapping[str, JsonValue]
    intended_at: datetime
    deadline_at: datetime | None = None

    def __post_init__(self) -> None:
        for field in ("action_id", "session_id", "action_kind"):
            require_identifier(getattr(self, field), field)
        require_revision(self.game_state_revision, "game_state_revision")
        require_revision(self.strategy_revision, "strategy_revision")
        object.__setattr__(self, "parameters", freeze_json(dict(self.parameters)))
        require_aware(self.intended_at, "intended_at")
        if self.deadline_at is not None:
            require_aware(self.deadline_at, "deadline_at")


@dataclass(frozen=True, slots=True)
class GameActionReport:
    action_id: str
    session_id: str
    status: GameActionExecutionStatus
    effect_state: GameActionEffectState
    applied_at: datetime | None
    game_state_revision_after: int | None
    sanitized_diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.action_id, "action_id")
        require_identifier(self.session_id, "session_id")
        if not isinstance(self.status, GameActionExecutionStatus) or not isinstance(
            self.effect_state, GameActionEffectState
        ):
            raise ValueError("effect_state が不正です")
        if self.applied_at is not None:
            require_aware(self.applied_at, "applied_at")
        require_revision(self.game_state_revision_after, "game_state_revision_after", optional=True)
        allowed_effects = {
            GameActionExecutionStatus.SUCCEEDED: {GameActionEffectState.APPLIED},
            GameActionExecutionStatus.FAILED: {
                GameActionEffectState.NOT_APPLIED,
                GameActionEffectState.AMBIGUOUS,
                GameActionEffectState.FAILED,
            },
            GameActionExecutionStatus.CANCELLED: {
                GameActionEffectState.NOT_APPLIED,
                GameActionEffectState.AMBIGUOUS,
            },
            GameActionExecutionStatus.TIMED_OUT: {GameActionEffectState.AMBIGUOUS},
            GameActionExecutionStatus.STALE: {
                GameActionEffectState.APPLIED,
                GameActionEffectState.AMBIGUOUS,
            },
            GameActionExecutionStatus.UNKNOWN_EFFECT: {GameActionEffectState.AMBIGUOUS},
        }
        if self.effect_state not in allowed_effects[self.status]:
            raise ValueError("action report effect truth が不正です")
        if self.effect_state is GameActionEffectState.APPLIED and (
            self.applied_at is None or self.game_state_revision_after is None
        ):
            raise ValueError("applied action report が不正です")
        if self.effect_state is GameActionEffectState.NOT_APPLIED and (
            self.applied_at is not None or self.game_state_revision_after is not None
        ):
            raise ValueError("not applied action report が不正です")
        object.__setattr__(
            self,
            "sanitized_diagnostics",
            _refs(self.sanitized_diagnostics, "sanitized_diagnostics"),
        )


@dataclass(frozen=True, slots=True)
class GameObservationEvent:
    event_id: str
    session_id: str
    category: GameObservationCategory
    salience_hint: float
    subject_refs: tuple[str, ...]
    game_state_revision: int
    observed_at: datetime
    bounded_payload: JsonValue

    def __post_init__(self) -> None:
        require_identifier(self.event_id, "event_id")
        require_identifier(self.session_id, "session_id")
        if not isinstance(self.category, GameObservationCategory):
            raise ValueError("category が不正です")
        if (
            type(self.salience_hint) not in (int, float)
            or not isfinite(self.salience_hint)
            or not 0 <= self.salience_hint <= 1
        ):
            raise ValueError("salience_hint が不正です")
        object.__setattr__(self, "salience_hint", float(self.salience_hint))
        object.__setattr__(self, "subject_refs", _refs(self.subject_refs, "subject_refs"))
        require_revision(self.game_state_revision, "game_state_revision")
        require_aware(self.observed_at, "observed_at")
        object.__setattr__(self, "bounded_payload", freeze_json(self.bounded_payload))
