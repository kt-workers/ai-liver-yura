from __future__ import annotations

import threading
from dataclasses import dataclass

from app.domain.body_awakening_affect import BodyAwakeningAffect
from app.domain.emotions.emotion_state import EmotionState
from app.runtime.agent_state import AgentState
from app.runtime.body_awakening_affect_projector import BodyAwakeningAffectProjector


@dataclass(frozen=True, slots=True)
class BodyCausalStateSnapshot:
    emotion: EmotionState
    awakening: BodyAwakeningAffect


class LatestBodyEmotionStateStore:
    """Core更新とBody Tickの間で最新の有限Body因果Snapshotを共有する。

    既存の ``snapshot()`` はEmotionだけを返す互換APIとして維持する。
    """

    def __init__(self, initial: EmotionState | None = None) -> None:
        self._lock = threading.RLock()
        self._emotion = initial or EmotionState()
        self._awakening = BodyAwakeningAffect()

    def update(
        self,
        emotion: EmotionState,
        *,
        awakening: BodyAwakeningAffect | None = None,
    ) -> None:
        if not isinstance(emotion, EmotionState):
            raise TypeError("emotion must be EmotionState")
        if awakening is not None and not isinstance(awakening, BodyAwakeningAffect):
            raise TypeError("awakening must be BodyAwakeningAffect")
        with self._lock:
            self._emotion = emotion
            if awakening is not None:
                self._awakening = awakening

    def snapshot(self) -> EmotionState:
        with self._lock:
            return self._emotion

    def causal_snapshot(self) -> BodyCausalStateSnapshot:
        with self._lock:
            return BodyCausalStateSnapshot(
                emotion=self._emotion,
                awakening=self._awakening,
            )

    def awakening_snapshot(self) -> BodyAwakeningAffect:
        with self._lock:
            return self._awakening


class BodyAgentStateObserver:
    """AgentStateからBodyが必要な有限因果状態だけを共有Storeへ転送する。"""

    def __init__(
        self,
        store: LatestBodyEmotionStateStore,
        *,
        awakening_projector: BodyAwakeningAffectProjector | None = None,
    ) -> None:
        if not isinstance(store, LatestBodyEmotionStateStore):
            raise TypeError("store must be LatestBodyEmotionStateStore")
        self._store = store
        self._awakening_projector = (
            awakening_projector or BodyAwakeningAffectProjector()
        )

    def __call__(self, state: AgentState) -> None:
        if not isinstance(state, AgentState):
            raise TypeError("state must be AgentState")
        self._store.update(
            state.current_emotion,
            awakening=self._awakening_projector.project(state.awakening_state),
        )


__all__ = [
    "BodyAgentStateObserver",
    "BodyCausalStateSnapshot",
    "LatestBodyEmotionStateStore",
]
