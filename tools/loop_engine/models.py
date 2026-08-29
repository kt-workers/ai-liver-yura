"""Loop Engineering制御系で使用する型付き・秘密情報を含まない契約。"""

from __future__ import annotations

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
    NO_OP_MUTATION_FORBIDDEN = "NO_OP_MUTATION_FORBIDDEN"
    UNKNOWN_WRITE_IDENTITY_FORBIDDEN = "UNKNOWN_WRITE_IDENTITY_FORBIDDEN"


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


class LoopHealthKind(str, Enum):
    REPEATED_FAILURE = "REPEATED_FAILURE"
    NO_PROGRESS = "NO_PROGRESS"
    MANUAL_INTERVENTION = "MANUAL_INTERVENTION"
    MANUAL_OPERATION_REPEAT = "MANUAL_OPERATION_REPEAT"
    STALE_STATE_RECURRENCE = "STALE_STATE_RECURRENCE"
    DUPLICATE_SCHEDULING = "DUPLICATE_SCHEDULING"
    RECOVERY_REPETITION = "RECOVERY_REPETITION"


class ImprovementSeverity(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"


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
    checkpoint_identity: str | None = None


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
    dependency_completion_identities: tuple[str, ...] = ()
    checkpoint_identity: str | None = None

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
class LoopHealthEvent:
    kind: LoopHealthKind
    fingerprint: str
    occurrence_count: int
    affected_work_ids: tuple[int, ...] = ()
    source_refs: tuple[str, ...] = ()
    blocked_work_count: int = 0
    manual_intervention_required: bool = False


@dataclass(frozen=True, slots=True)
class ExistingImprovementIssue:
    issue_number: int
    improvement_key: str
    state: str
    project_configured: bool = True


@dataclass(frozen=True, slots=True)
class ImprovementCandidate:
    improvement_key: str
    kind: LoopHealthKind
    severity: ImprovementSeverity
    title: str
    problem: str
    evidence_refs: tuple[str, ...]
    affected_work_ids: tuple[int, ...]
    start_date: str
    target_date: str


@dataclass(frozen=True, slots=True)
class ImprovementIssueIntent:
    repository: str
    project_number: int
    label: str
    status: str
    area: str
    issue_level: str
    candidate: ImprovementCandidate


@dataclass(frozen=True, slots=True)
class ImprovementPublishResult:
    issue_number: int
    issue_url: str
    created: bool
    project_configured: bool


@dataclass(frozen=True, slots=True)
class ImprovementPublishFailure:
    improvement_key: str
    reason: str = "IMPROVEMENT_PUBLISH_FAILED"


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
    health_events: tuple[LoopHealthEvent, ...] = ()
    open_improvement_issues: tuple[ExistingImprovementIssue, ...] = ()
    checkpoint_improvement_keys: tuple[str, ...] = ()


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
    health_events: tuple[LoopHealthEvent, ...] = ()
    improvement_candidates: tuple[ImprovementCandidate, ...] = ()


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
