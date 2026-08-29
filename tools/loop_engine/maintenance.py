"""自己改善Workの公開処理を統括する。"""

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
        """決定論的な改善Issue作成意図を1件公開する。"""


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
                # 生の例外文章にはコマンドや提供元の詳細が含まれる可能性がある。
                # 公開結果には安定した理由だけを残す。
                failures.append(ImprovementPublishFailure(candidate.improvement_key))
        return MaintenancePublication(tuple(published), tuple(failures))

    def run(self, decision: SupervisorDecision) -> MaintenancePublication:
        return self.publish_candidates(decision.improvement_candidates)


@dataclass(slots=True)
class LoopMaintenanceCycle:
    """自己改善Workの公開を含む、通常Loop制御系の1回分の処理。"""

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
