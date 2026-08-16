from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from .contracts import (
    AttentionIngressOperation,
    AttentionIngressSignal,
    ExecutiveTriggerEligibility,
)
from .ports import AttentionIngressPort, AttentionTriggerPort


class AttentionCoordinator:
    """attention laneからExecutive laneへclaimを渡す同期Application境界。"""

    def __init__(
        self,
        ingress: AttentionIngressPort,
        trigger: AttentionTriggerPort,
        enqueue_executive: Callable[[ExecutiveTriggerEligibility], None],
    ) -> None:
        self._ingress = ingress
        self._trigger = trigger
        self._enqueue_executive = enqueue_executive

    def handle(
        self,
        signal: AttentionIngressSignal,
        current_goal_revision: int,
        now: datetime,
    ) -> ExecutiveTriggerEligibility | None:
        if signal.operation is AttentionIngressOperation.RESOLVE:
            self._ingress.resolve(signal)
        else:
            self._ingress.offer(signal)
        claimed = self._trigger.claim_next(current_goal_revision, now)
        if claimed is not None:
            self._enqueue_executive(claimed)
        return claimed
