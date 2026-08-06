from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.runtime.agent_life_service import AgentLifeService
from app.runtime.agent_state import AgentState
from app.runtime.agent_state_observer_fanout import AgentStateObserverFanout
from app.runtime.body_emotion_bridge import get_body_agent_state_observer


class BodyAwareAgentLifeService(AgentLifeService):
    """既存AgentLifeServiceへBody Emotion observerだけをCompositionする。"""

    def __init__(
        self,
        *args: Any,
        state_observer: Callable[[AgentState], None] | None = None,
        **kwargs: Any,
    ) -> None:
        observers: list[Callable[[AgentState], None]] = []
        if state_observer is not None:
            observers.append(state_observer)
        observers.append(get_body_agent_state_observer())
        super().__init__(
            *args,
            state_observer=AgentStateObserverFanout(observers),
            **kwargs,
        )
