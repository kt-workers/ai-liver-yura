from __future__ import annotations

from app.runtime.body_emotion_state_store import (
    BodyAgentStateObserver,
    LatestBodyEmotionStateStore,
)

_BODY_EMOTION_STORE = LatestBodyEmotionStateStore()
_BODY_AGENT_STATE_OBSERVER = BodyAgentStateObserver(_BODY_EMOTION_STORE)


def get_body_emotion_state_store() -> LatestBodyEmotionStateStore:
    return _BODY_EMOTION_STORE


def get_body_agent_state_observer() -> BodyAgentStateObserver:
    return _BODY_AGENT_STATE_OBSERVER
