"""Self-improvement publication orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .github_issues import improvement_intent
from .models import (
    ImprovementCandidate,
    ImprovementIssueIntent,
    ImprovementPublishResult,
    SupervisorDecision,
)


class ImprovementPublisher(Protocol):
    def publish(self, intent: ImprovementIssueIntent) -> ImprovementPublishResult:
        """Publish one deterministic improvement issue intent."""


@dataclass(slots=True)
class SelfImprovementController:
    publisher: ImprovementPublisher

    def publish_candidates(
        self,
        candidates: tuple[ImprovementCandidate, ...],
    ) -> tuple[ImprovementPublishResult, ...]:
        return tuple(
            self.publisher.publish(improvement_intent(candidate))
            for candidate in candidates
        )

    def run(self, decision: SupervisorDecision) -> tuple[ImprovementPublishResult, ...]:
        return self.publish_candidates(decision.improvement_candidates)
