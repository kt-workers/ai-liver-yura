"""Conflict reconciliation over already-observed live state."""

from __future__ import annotations

from .models import ConflictKind, LineageClassification, ObservationEpoch

_PROJECT_NUMBER = 7


def reconcile_global(epoch: ObservationEpoch) -> tuple[ConflictKind, ...]:
    conflicts: list[ConflictKind] = []
    if not epoch.authorities_available:
        conflicts.append(ConflictKind.AUTHORITY_UNAVAILABLE)
    if epoch.project_number != _PROJECT_NUMBER:
        conflicts.append(ConflictKind.FORBIDDEN_PROJECT_IDENTITY)
    elif not epoch.project_available:
        conflicts.append(ConflictKind.PROJECT_AUTHORITY_UNAVAILABLE)
    if not epoch.canonical_designs:
        conflicts.append(ConflictKind.CANONICAL_DESIGN_UNRESOLVED)
    elif any(item.expected_blob_sha != item.live_blob_sha for item in epoch.canonical_designs):
        conflicts.append(ConflictKind.CANONICAL_DESIGN_MISMATCH)
    if epoch.mission.checkpoint_is_stale:
        conflicts.append(ConflictKind.MISSION_CHECKPOINT_STALE)
    return tuple(dict.fromkeys(conflicts))


def reconcile_work(epoch: ObservationEpoch, issue_number: int) -> tuple[ConflictKind, ...]:
    """Return only conflicts that make one observed Work unsafe to select."""
    conflicts: list[ConflictKind] = []
    work = next((item for item in epoch.works if item.issue_number == issue_number), None)
    if work is None or not work.checkpoint_matches_live:
        conflicts.append(ConflictKind.CHECKPOINT_LIVE_MISMATCH)
    matching = [item for item in epoch.lineages if item.work_issue == issue_number]
    if sum(item.classification is LineageClassification.CANONICAL for item in matching) > 1:
        conflicts.append(ConflictKind.MULTIPLE_ACTIVE_LINEAGES)
    if any(item.classification is LineageClassification.UNKNOWN for item in matching):
        conflicts.append(ConflictKind.UNKNOWN_LINEAGE)
    for lineage in matching:
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


def reconcile(epoch: ObservationEpoch) -> tuple[ConflictKind, ...]:
    """Aggregate view for reporting; scheduling must use scoped functions."""
    conflicts = list(reconcile_global(epoch))
    for work in epoch.works:
        conflicts.extend(reconcile_work(epoch, work.issue_number))
    return tuple(dict.fromkeys(conflicts))
