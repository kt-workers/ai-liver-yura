from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .contracts import AttentionFocusState, AttentionIngressSignal, ExecutiveTriggerEligibility


class AttentionIngressPort(Protocol):
    def offer(self, signal: AttentionIngressSignal) -> AttentionFocusState: ...

    def resolve(self, signal: AttentionIngressSignal) -> AttentionFocusState: ...


class AttentionTriggerPort(Protocol):
    def claim_next(
        self, current_goal_revision: int, now: datetime
    ) -> ExecutiveTriggerEligibility | None: ...
