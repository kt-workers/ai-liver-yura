"""Self-improvement publication orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from .github_issues import improvement_intent
from .models import (
    ImprovementCandidate,
    ImprovementIssueIntent,
    ImprovementPublishFailure,
    ImprovementPublishResult,
    ObservationEpoch,
    SupervisorDecision,
)
from .supervisor import MissionSupervisor


class ImprovementPublisher(Protocol):
    def publish(self, intent: ImprovementIssueIntent) -> ImprovementPublishResult:
        """Publish one deterministic improvement issue intent."""


@dataclass(frozen=True, slots=True)
class MaintenancePublication:
    published: tuple[ImprovementPublishResult, ...]
    failures: tuple[ImprovementPublishFailure, ...]


@dataclass(frozen=True, slots=True)
class LoopMaintenanceCycleResult:
    decision: SupervisorDecision
    publication: MaintenancePublication


@dataclass(slots=True)
class SelfImprovementController:
    publisher: ImprovementPublisher

    def publish_candidates(
        self,
        candidates: tuple[ImprovementCandidate, ...],
    ) -> MaintenancePublication:
        published: list[ImprovementPublishResult] = []
        failures: list[ImprovementPublishFailure] = []
        for candidate in candidates:
            try:
                published.append(self.publisher.publish(improvement_intent(candidate)))
            except Exception:
                # Raw exception text can contain command/provider details. Keep only a stable reason.
                failures.append(ImprovementPublishFailure(candidate.improvement_key))
        return MaintenancePublication(tuple(published), tuple(failures))

    def run(self, decision: SupervisorDecision) -> MaintenancePublication:
        return self.publish_candidates(decision.improvement_candidates)


@dataclass(slots=True)
class LoopMaintenanceCycle:
    """One normal loop control-plane iteration including self-improvement publication."""

    supervisor: MissionSupervisor
    controller: SelfImprovementController

    def run(
        self,
        epoch: ObservationEpoch,
        *,
        planning_date: date | None = None,
    ) -> LoopMaintenanceCycleResult:
        decision = self.supervisor.decide(epoch, planning_date=planning_date)
        publication = self.controller.run(decision)
        return LoopMaintenanceCycleResult(decision, publication)
