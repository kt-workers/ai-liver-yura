from __future__ import annotations

import threading

from app.domain.emotions.emotion_state import EmotionState
from app.runtime.agent_state import AgentState


class LatestBodyEmotionStateStore:
    """同期Core更新と非同期Body Tickの間で最新Emotion Snapshotを共有する。"""

    def __init__(self, initial: EmotionState | None = None) -> None:
        self._lock = threading.RLock()
        self._emotion = initial or EmotionState()

    def update(self, emotion: EmotionState) -> None:
        if not isinstance(emotion, EmotionState):
            raise TypeError("emotion must be EmotionState")
        with self._lock:
            self._emotion = emotion

    def snapshot(self) -> EmotionState:
        with self._lock:
            return self._emotion


class BodyAgentStateObserver:
    """AgentStateから確定済みEmotionだけをBody Storeへ転送する。"""

    def __init__(self, store: LatestBodyEmotionStateStore) -> None:
        if not isinstance(store, LatestBodyEmotionStateStore):
            raise TypeError("store must be LatestBodyEmotionStateStore")
        self._store = store

    def __call__(self, state: AgentState) -> None:
        if not isinstance(state, AgentState):
            raise TypeError("state must be AgentState")
        self._store.update(state.current_emotion)
