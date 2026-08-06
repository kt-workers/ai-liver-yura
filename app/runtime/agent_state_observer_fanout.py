from __future__ import annotations

from collections.abc import Callable, Iterable

from app.runtime.agent_state import AgentState
from app.utils.trace import TraceLogger

AgentStateObserver = Callable[[AgentState], None]


class AgentStateObserverFanout:
    """AgentState確定通知を独立Observerへ配送する。"""

    def __init__(
        self,
        observers: Iterable[AgentStateObserver],
        *,
        trace_logger: TraceLogger | None = None,
    ) -> None:
        self._observers = tuple(observers)
        if not all(callable(observer) for observer in self._observers):
            raise TypeError("observers must contain callables")
        self._trace_logger = trace_logger or TraceLogger()

    def __call__(self, state: AgentState) -> None:
        failures = 0
        for observer in self._observers:
            try:
                observer(state)
            except Exception as error:
                failures += 1
                self._trace_logger.warning(
                    "agent_state_observer_fanout:observer_failed",
                    observer=getattr(
                        observer,
                        "__qualname__",
                        type(observer).__name__,
                    ),
                    error_type=type(error).__name__,
                )
        if failures:
            self._trace_logger.warning(
                "agent_state_observer_fanout:completed_with_failures",
                observer_count=len(self._observers),
                failure_count=failures,
            )
