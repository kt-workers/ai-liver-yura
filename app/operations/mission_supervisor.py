"""Deterministic, product-runtime-independent Mission Supervisor core."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum


class ConflictKind(str, Enum):
    AUTHORITY_UNAVAILABLE = "AUTHORITY_UNAVAILABLE"
    PROJECT_AUTHORITY_UNAVAILABLE = "PROJECT_AUTHORITY_UNAVAILABLE"
    CANONICAL_DESIGN_UNRESOLVED = "CANONICAL_DESIGN_UNRESOLVED"
    CANONICAL_DESIGN_MISMATCH = "CANONICAL_DESIGN_MISMATCH"
    MULTIPLE_ACTIVE_LINEAGES = "MULTIPLE_ACTIVE_LINEAGES"
    UNKNOWN_LINEAGE = "UNKNOWN_LINEAGE"
    BASE_SHA_MISMATCH = "BASE_SHA_MISMATCH"
    HEAD_SHA_MISMATCH = "HEAD_SHA_MISMATCH"
    UNEXPLAINED_SHA_CHANGE = "UNEXPLAINED_SHA_CHANGE"
    CHECKPOINT_LIVE_MISMATCH = "CHECKPOINT_LIVE_MISMATCH"
    MISSION_CHECKPOINT_STALE = "MISSION_CHECKPOINT_STALE"
    REVIEW_HEAD_MISMATCH = "REVIEW_HEAD_MISMATCH"
    CI_HEAD_MISMATCH = "CI_HEAD_MISMATCH"
    FORBIDDEN_PROJECT_IDENTITY = "FORBIDDEN_PROJECT_IDENTITY"
    STALE_WRITE_GATE = "STALE_WRITE_GATE"
    MUTATION_EFFECT_MISMATCH = "MUTATION_EFFECT_MISMATCH"
    DIRECT_TRUNK_WRITE_FORBIDDEN = "DIRECT_TRUNK_WRITE_FORBIDDEN"


class RunDisposition(str, Enum):
    CONTINUE = "CONTINUE"
    YIELD_EXTERNAL = "YIELD_EXTERNAL"
    INTERVENTION_REQUIRED = "INTERVENTION_REQUIRED"
    MISSION_COMPLETE = "MISSION_COMPLETE"


class LineageClassification(str, Enum):
    CANONICAL = "CANONICAL"
    SUPERSEDED = "SUPERSEDED"
    VALIDATION_ONLY = "VALIDATION_ONLY"
    CI_ONLY = "CI_ONLY"
    ABANDONED = "ABANDONED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    source_kind: str
    stable_id: str
    source_revision: str


@dataclass(frozen=True, slots=True)
class MissionSnapshot:
    identity: SourceIdentity
    current_work_id: int | None
    checkpoint_is_stale: bool = False
    root_completion_evidence_complete: bool = False


@dataclass(frozen=True, slots=True)
class WorkSnapshot:
    identity: SourceIdentity
    issue_number: int
    issue_open: bool
    project_status: str
    priority: str | None
    dependencies_satisfied: bool
    canonical_design_resolved: bool
    actionable: bool
    wait_only: bool = False
    wait_reason: str | None = None
    checkpoint_matches_live: bool = True

    @property
    def dependency_ready(self) -> bool:
        return (
            self.issue_open
            and self.dependencies_satisfied
            and self.canonical_design_resolved
            and self.project_status not in {"Blocked", "Done"}
        )


@dataclass(frozen=True, slots=True)
class LineageSnapshot:
    identity: SourceIdentity
    work_issue: int
    classification: LineageClassification
    branch_ref: str | None
    base_ref: str | None
    base_sha: str | None
    head_sha: str | None
    expected_base_sha: str | None = None
    checkpoint_head_sha: str | None = None
    ci_head_sha: str | None = None
    review_head_sha: str | None = None
    explainable_advance: bool = True


@dataclass(frozen=True, slots=True)
class CanonicalDesignSnapshot:
    identity: SourceIdentity
    path: str
    expected_blob_sha: str
    live_blob_sha: str
    authority_owner: int


@dataclass(frozen=True, slots=True)
class ObservationEpoch:
    observation_id: str
    repository: str
    canonical_trunk_ref: str
    canonical_trunk_sha: str
    project_number: int
    project_available: bool
    authorities_available: bool
    mission: MissionSnapshot
    works: tuple[WorkSnapshot, ...]
    lineages: tuple[LineageSnapshot, ...]
    canonical_designs: tuple[CanonicalDesignSnapshot, ...]
    checkpoint_schedule_keys: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResumeCertificate:
    gate: str
    target_issue: int | None
    canonical_design_refs: tuple[str, ...]
    active_lineage: str | None
    working_branch: str | None
    base_sha: str | None
    head_sha: str | None
    current_status: str
    last_verification: tuple[str, ...]
    next_action: str
    conflicts: tuple[ConflictKind, ...]
    observation_id: str


@dataclass(frozen=True, slots=True)
class TaskPacket:
    packet_id: str
    schedule_key: str
    observation_id: str
    authority: tuple[str, ...]
    scope: tuple[str, ...]
    non_goals: tuple[str, ...]
    exact_target: tuple[str, ...]
    dependencies: tuple[str, ...]
    acceptance_checks: tuple[str, ...]
    risk_boundary: tuple[str, ...]
    active_lineage: str | None
    expected_next_transition: str


@dataclass(frozen=True, slots=True)
class SupervisorDecision:
    observation_id: str
    disposition: RunDisposition
    selected_work_id: int | None
    resume_certificate: ResumeCertificate
    task_packet: TaskPacket | None
    duplicate_suppressed: bool


@dataclass(frozen=True, slots=True)
class WriteIntent:
    intent_id: str
    target_kind: str
    target_identity: str
    mutation_kind: str
    expected_preconditions: tuple[tuple[str, str], ...]
    expected_effect: tuple[tuple[str, str], ...]
    source_observation_id: str


@dataclass(frozen=True, slots=True)
class WriteGateResult:
    allowed: bool
    conflict: ConflictKind | None


class MissionSupervisor:
    """Makes decisions from supplied live observations; it has no GitHub transport."""

    _REPOSITORY = "ktan514/ai-liver-yura"
    _PROJECT_NUMBER = 7
    _PRIORITY = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}

    def reconcile(self, epoch: ObservationEpoch) -> tuple[ConflictKind, ...]:
        conflicts: list[ConflictKind] = []
        if not epoch.authorities_available:
            conflicts.append(ConflictKind.AUTHORITY_UNAVAILABLE)
        if epoch.project_number != self._PROJECT_NUMBER:
            conflicts.append(ConflictKind.FORBIDDEN_PROJECT_IDENTITY)
        elif not epoch.project_available:
            conflicts.append(ConflictKind.PROJECT_AUTHORITY_UNAVAILABLE)
        if not epoch.canonical_designs:
            conflicts.append(ConflictKind.CANONICAL_DESIGN_UNRESOLVED)
        elif any(item.expected_blob_sha != item.live_blob_sha for item in epoch.canonical_designs):
            conflicts.append(ConflictKind.CANONICAL_DESIGN_MISMATCH)
        if epoch.mission.checkpoint_is_stale:
            conflicts.append(ConflictKind.MISSION_CHECKPOINT_STALE)
        if any(not work.checkpoint_matches_live for work in epoch.works):
            conflicts.append(ConflictKind.CHECKPOINT_LIVE_MISMATCH)
        for work in epoch.works:
            matching = [
                lineage for lineage in epoch.lineages if lineage.work_issue == work.issue_number
            ]
            if sum(item.classification is LineageClassification.CANONICAL for item in matching) > 1:
                conflicts.append(ConflictKind.MULTIPLE_ACTIVE_LINEAGES)
            if any(item.classification is LineageClassification.UNKNOWN for item in matching):
                conflicts.append(ConflictKind.UNKNOWN_LINEAGE)
        for lineage in epoch.lineages:
            if lineage.expected_base_sha and lineage.base_sha != lineage.expected_base_sha:
                conflicts.append(ConflictKind.BASE_SHA_MISMATCH)
            if lineage.checkpoint_head_sha and lineage.head_sha != lineage.checkpoint_head_sha:
                conflicts.append(ConflictKind.HEAD_SHA_MISMATCH)
            if lineage.head_sha and not lineage.explainable_advance:
                conflicts.append(ConflictKind.UNEXPLAINED_SHA_CHANGE)
            if lineage.ci_head_sha and lineage.ci_head_sha != lineage.head_sha:
                conflicts.append(ConflictKind.CI_HEAD_MISMATCH)
            if lineage.review_head_sha and lineage.review_head_sha != lineage.head_sha:
                conflicts.append(ConflictKind.REVIEW_HEAD_MISMATCH)
        return tuple(dict.fromkeys(conflicts))

    def decide(self, epoch: ObservationEpoch) -> SupervisorDecision:
        conflicts = self.reconcile(epoch)
        selected = None if conflicts else self._select_work(epoch)
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
        key = self.schedule_key(epoch, selected, "IMPLEMENT")
        if key in epoch.checkpoint_schedule_keys:
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

    def schedule_key(self, epoch: ObservationEpoch, work: WorkSnapshot, transition: str) -> str:
        lineage = self._canonical_lineage(epoch, work.issue_number)
        state = {
            "canonical_designs": sorted(
                (item.identity.stable_id, item.live_blob_sha) for item in epoch.canonical_designs
            ),
            "lineage": (
                lineage.classification.value if lineage else None,
                lineage.base_sha if lineage else None,
                lineage.head_sha if lineage else None,
                lineage.ci_head_sha if lineage else None,
                lineage.review_head_sha if lineage else None,
            ),
            "issue": work.issue_number,
            "mission": (epoch.mission.identity.stable_id, epoch.mission.identity.source_revision),
            "priority": work.priority,
            "project_number": epoch.project_number,
            "project_status": work.project_status,
            "source_revision": work.identity.source_revision,
            "transition": transition,
        }
        return hashlib.sha256(
            json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def validate_write_gate(
        self,
        intent: WriteIntent,
        fresh_preconditions: Mapping[str, str],
        readback_effect: Mapping[str, str] | None = None,
    ) -> WriteGateResult:
        if intent.target_kind == "project" and intent.target_identity != "7":
            return WriteGateResult(False, ConflictKind.FORBIDDEN_PROJECT_IDENTITY)
        if intent.target_kind == "branch" and intent.target_identity == "rebuild/v2-foundation":
            return WriteGateResult(False, ConflictKind.DIRECT_TRUNK_WRITE_FORBIDDEN)
        if any(
            fresh_preconditions.get(key) != value for key, value in intent.expected_preconditions
        ):
            return WriteGateResult(False, ConflictKind.STALE_WRITE_GATE)
        if readback_effect is not None and any(
            readback_effect.get(key) != value for key, value in intent.expected_effect
        ):
            return WriteGateResult(False, ConflictKind.MUTATION_EFFECT_MISMATCH)
        return WriteGateResult(True, None)

    def _select_work(self, epoch: ObservationEpoch) -> WorkSnapshot | None:
        current = next(
            (item for item in epoch.works if item.issue_number == epoch.mission.current_work_id),
            None,
        )
        if current is not None and current.dependency_ready and current.actionable:
            return current
        candidates = [item for item in epoch.works if item.dependency_ready and item.actionable]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda item: (self._priority(item), self._status(item), item.issue_number),
        )

    def _certificate(
        self,
        epoch: ObservationEpoch,
        work: WorkSnapshot | None,
        conflicts: Sequence[ConflictKind],
    ) -> ResumeCertificate:
        lineage = self._canonical_lineage(epoch, work.issue_number) if work else None
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
        lineage = self._canonical_lineage(epoch, work.issue_number)
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

    def _canonical_lineage(
        self, epoch: ObservationEpoch, issue_number: int
    ) -> LineageSnapshot | None:
        return next(
            (
                item
                for item in epoch.lineages
                if item.work_issue == issue_number
                and item.classification is LineageClassification.CANONICAL
            ),
            None,
        )

    def _priority(self, work: WorkSnapshot) -> int:
        return self._PRIORITY.get(work.priority or "", 4)

    @staticmethod
    def _status(work: WorkSnapshot) -> int:
        return 0 if work.project_status == "In progress" else 1
