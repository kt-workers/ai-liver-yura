"""Composition root for deterministic Loop Engineering decisions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date

from .health import advance_health, plan_improvements
from .models import (
    ConflictKind,
    ObservationEpoch,
    ResumeCertificate,
    RunDisposition,
    SupervisorDecision,
    TaskPacket,
    WorkSnapshot,
    WriteGateResult,
    WriteIntent,
)
from .reconciliation import reconcile, reconcile_global, reconcile_work
from .scheduler import canonical_lineage, is_duplicate, schedule_key, select_work
from .write_gate import validate


class MissionSupervisor:
    """Makes decisions from supplied live observations; it has no GitHub transport."""

    def reconcile(self, epoch: ObservationEpoch) -> tuple[ConflictKind, ...]:
        return reconcile(epoch)

    def decide(
        self,
        epoch: ObservationEpoch,
        *,
        planning_date: date | None = None,
    ) -> SupervisorDecision:
        decision = self._decide_primary(epoch)
        health_events = advance_health(
            epoch.health_events,
            conflicts=decision.resume_certificate.conflicts,
            disposition=decision.disposition,
            duplicate_suppressed=decision.duplicate_suppressed,
            selected_work_id=decision.selected_work_id,
        )
        improvements = plan_improvements(
            health_events,
            existing_issues=epoch.open_improvement_issues,
            checkpoint_keys=epoch.checkpoint_improvement_keys,
            planning_date=planning_date or date.today(),
        )
        return replace(
            decision,
            health_events=health_events,
            improvement_candidates=improvements,
        )

    def _decide_primary(self, epoch: ObservationEpoch) -> SupervisorDecision:
        global_conflicts = reconcile_global(epoch)
        eligible = tuple(
            work
            for work in epoch.works
            if not reconcile_work(epoch, work.issue_number)
        )
        selectable_epoch = replace(epoch, works=eligible)
        selected = None if global_conflicts else select_work(selectable_epoch)
        certificate = self._certificate(epoch, selected, global_conflicts)
        if global_conflicts:
            return SupervisorDecision(
                epoch.observation_id,
                RunDisposition.INTERVENTION_REQUIRED,
                None,
                certificate,
                None,
                False,
            )
        if selected is None:
            disposition = (
                RunDisposition.MISSION_COMPLETE
                if epoch.mission.root_completion_evidence_complete
                else RunDisposition.YIELD_EXTERNAL
            )
            return SupervisorDecision(
                epoch.observation_id, disposition, None, certificate, None, False
            )
        key = schedule_key(selectable_epoch, selected, "IMPLEMENT")
        if is_duplicate(selectable_epoch, key):
            return SupervisorDecision(
                epoch.observation_id,
                RunDisposition.YIELD_EXTERNAL,
                selected.issue_number,
                certificate,
                None,
                True,
            )
        return SupervisorDecision(
            epoch.observation_id,
            RunDisposition.CONTINUE,
            selected.issue_number,
            certificate,
            self._packet(selectable_epoch, selected, key),
            False,
        )

    def validate_write_gate(
        self,
        intent: WriteIntent,
        fresh_preconditions: Mapping[str, str],
        readback_effect: Mapping[str, str] | None = None,
    ) -> WriteGateResult:
        return validate(intent, fresh_preconditions, readback_effect)

    def _certificate(
        self,
        epoch: ObservationEpoch,
        work: WorkSnapshot | None,
        conflicts: Sequence[ConflictKind],
    ) -> ResumeCertificate:
        lineage = canonical_lineage(epoch, work.issue_number) if work else None
        return ResumeCertificate(
            "STOP" if conflicts else "PASS",
            work.issue_number if work else None,
            tuple(item.path for item in epoch.canonical_designs),
            lineage.identity.stable_id if lineage else None,
            lineage.branch_ref if lineage else None,
            lineage.base_sha if lineage else None,
            lineage.head_sha if lineage else None,
            work.project_status if work else "no actionable work",
            tuple(item.identity.stable_id for item in epoch.canonical_designs),
            "reconcile conflicts" if conflicts else "implement selected work",
            tuple(conflicts),
            epoch.observation_id,
        )

    def _packet(self, epoch: ObservationEpoch, work: WorkSnapshot, key: str) -> TaskPacket:
        lineage = canonical_lineage(epoch, work.issue_number)
        exact = (f"base:{lineage.base_sha}" if lineage and lineage.base_sha else "base:none",)
        return TaskPacket(
            f"packet:{key[:16]}",
            key,
            epoch.observation_id,
            ("#207", "#317", "#450", "#462", f"#{work.issue_number}"),
            ("development tooling", "deterministic supervisor"),
            ("OpenAI reviewer transport", "PostgreSQL store", "product runtime scheduler"),
            exact,
            ("live dependency evidence",),
            ("targeted tests", "Ruff", "strict Mypy", "full pytest", "exact-head CI"),
            ("Project #7 only", "no secrets", "no direct trunk write"),
            lineage.identity.stable_id if lineage else None,
            "IMPLEMENT",
        )
