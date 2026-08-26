"""Composition root for deterministic Loop Engineering decisions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

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
from .reconciliation import reconcile
from .scheduler import canonical_lineage, is_duplicate, schedule_key, select_work
from .write_gate import validate


class MissionSupervisor:
    """Makes decisions from supplied live observations; it has no GitHub transport."""

    def reconcile(self, epoch: ObservationEpoch) -> tuple[ConflictKind, ...]:
        return reconcile(epoch)

    def decide(self, epoch: ObservationEpoch) -> SupervisorDecision:
        conflicts = self.reconcile(epoch)
        selected = None if conflicts else select_work(epoch)
        certificate = self._certificate(epoch, selected, conflicts)
        if conflicts:
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
        key = schedule_key(epoch, selected, "IMPLEMENT")
        if is_duplicate(epoch, key):
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
            self._packet(epoch, selected, key),
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
