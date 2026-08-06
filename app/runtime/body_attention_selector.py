from __future__ import annotations

import random
from dataclasses import dataclass

from app.domain.body_attention import BodyAttentionCandidate
from app.domain.body_attention_intent import (
    BodyAttentionBehavior,
    BodyAttentionIntent,
)
from app.domain.body_motion_state import BodyInnerMotionState


@dataclass(frozen=True, slots=True)
class BodyAttentionSelection:
    target_id: str | None
    x: float
    y: float
    dwell_ms: int
    uses_candidate: bool


class BodyAttentionSelector:
    """注意候補から注視対象を選び、滞在時間だけを管理する。"""

    def __init__(self, *, seed: int | None = None) -> None:
        self._random = random.Random(seed)
        self._candidates: tuple[BodyAttentionCandidate, ...] = ()
        self._selected: BodyAttentionCandidate | None = None
        self._elapsed = 0.0
        self._dwell_target = 1.5

    @property
    def selected_target_id(self) -> str | None:
        return self._selected.candidate_id if self._selected is not None else None

    def set_candidates(
        self,
        candidates: tuple[BodyAttentionCandidate, ...] | list[BodyAttentionCandidate],
    ) -> None:
        normalized = tuple(candidates)
        if len(normalized) > 32:
            raise ValueError("at most 32 attention candidates are supported")
        if not all(isinstance(value, BodyAttentionCandidate) for value in normalized):
            raise TypeError("candidates must contain BodyAttentionCandidate values")
        identifiers = [value.candidate_id for value in normalized]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("attention candidate ids must be unique")
        self._candidates = normalized
        if self._selected is not None and self._find(self._selected.candidate_id) is None:
            self._selected = None
            self._elapsed = 0.0

    def step(
        self,
        *,
        dt_seconds: float,
        state: BodyInnerMotionState,
        intent: BodyAttentionIntent | None,
    ) -> BodyAttentionSelection:
        if not isinstance(state, BodyInnerMotionState):
            raise TypeError("state must be BodyInnerMotionState")
        if intent is not None and not isinstance(intent, BodyAttentionIntent):
            raise TypeError("intent must be BodyAttentionIntent")
        dt = max(1.0 / 240.0, min(0.1, float(dt_seconds)))
        self._elapsed += dt

        explicit = self._explicit_candidate(intent)
        if explicit is not None and self._selected is not explicit:
            self._selected = explicit
            self._elapsed = 0.0
            self._dwell_target = self._dwell_for(explicit, state)

        if self._should_reconsider(dt=dt, state=state, intent=intent):
            selected = self._choose(state=state, intent=intent)
            if selected is not self._selected:
                self._selected = selected
                self._elapsed = 0.0
            self._dwell_target = (
                self._dwell_for(selected, state)
                if selected is not None
                else self._random.uniform(0.8, 2.5)
            )

        selected = self._selected
        if selected is None:
            return BodyAttentionSelection(
                target_id=intent.target if intent is not None else None,
                x=0.0,
                y=0.0,
                dwell_ms=round(self._elapsed * 1000),
                uses_candidate=False,
            )
        return BodyAttentionSelection(
            target_id=selected.candidate_id,
            x=selected.x,
            y=selected.y,
            dwell_ms=round(self._elapsed * 1000),
            uses_candidate=True,
        )

    def _explicit_candidate(
        self,
        intent: BodyAttentionIntent | None,
    ) -> BodyAttentionCandidate | None:
        if intent is None or intent.behavior in {
            BodyAttentionBehavior.WANDER,
            BodyAttentionBehavior.SEARCH,
        }:
            return None
        return self._find(intent.target)

    def _should_reconsider(
        self,
        *,
        dt: float,
        state: BodyInnerMotionState,
        intent: BodyAttentionIntent | None,
    ) -> bool:
        if self._selected is None or self._elapsed >= self._dwell_target:
            return True
        if intent is not None and intent.behavior is BodyAttentionBehavior.MAINTAIN:
            return False
        reconsider_rate = 0.10 + state.curiosity * 0.34 + state.tension * 0.18
        if intent is not None:
            if intent.behavior is BodyAttentionBehavior.SEARCH:
                reconsider_rate += 0.22
            elif intent.behavior is BodyAttentionBehavior.WANDER:
                reconsider_rate += 0.12
        return self._elapsed >= 0.45 and self._random.random() < reconsider_rate * dt

    def _choose(
        self,
        *,
        state: BodyInnerMotionState,
        intent: BodyAttentionIntent | None,
    ) -> BodyAttentionCandidate | None:
        if not self._candidates:
            return None
        weighted: list[tuple[BodyAttentionCandidate, float]] = []
        for candidate in self._candidates:
            score = 0.12
            score += candidate.salience * 0.72
            score += candidate.novelty * state.curiosity * 0.82
            score += candidate.threat * state.tension * 0.95
            score += candidate.relevance * state.engagement * 0.88
            if self._selected is not None and candidate.candidate_id == self._selected.candidate_id:
                score += candidate.stability * 0.55
            avoidance = state.avoidance
            if intent is not None:
                if candidate.candidate_id == intent.target:
                    score += intent.engagement * 1.15
                    avoidance = max(avoidance, intent.avoidance)
                if intent.behavior is BodyAttentionBehavior.AVOID and candidate.candidate_id == intent.target:
                    score *= max(0.02, 1.0 - intent.avoidance * 0.92)
            score *= 1.0 - avoidance * candidate.relevance * 0.38
            weighted.append((candidate, max(0.01, score)))
        total = sum(weight for _, weight in weighted)
        cursor = self._random.random() * total
        for candidate, weight in weighted:
            cursor -= weight
            if cursor <= 0.0:
                return candidate
        return weighted[-1][0]

    def _dwell_for(
        self,
        candidate: BodyAttentionCandidate,
        state: BodyInnerMotionState,
    ) -> float:
        base = 0.65 + candidate.stability * 2.3
        base += state.engagement * candidate.relevance * 1.7
        base -= state.curiosity * candidate.novelty * 0.7
        base -= state.tension * candidate.threat * 0.45
        return max(0.45, min(4.8, base * self._random.uniform(0.78, 1.28)))

    def _find(self, candidate_id: str) -> BodyAttentionCandidate | None:
        return next(
            (
                value
                for value in self._candidates
                if value.candidate_id == candidate_id
            ),
            None,
        )
