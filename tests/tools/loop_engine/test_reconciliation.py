from tools.loop_engine.models import (
    CanonicalDesignSnapshot,
    ConflictKind,
    LineageClassification,
    LineageSnapshot,
    MissionSnapshot,
)
from tools.loop_engine.reconciliation import reconcile

from .conftest import epoch, identity, lineage


def test_live_checkpoint_consistency_has_no_conflicts() -> None:
    assert reconcile(epoch()) == ()


def test_stale_mission_checkpoint_and_project_unavailable_fail_closed() -> None:
    stale = epoch(mission=MissionSnapshot(identity("issue", "450"), 465, True))
    assert ConflictKind.MISSION_CHECKPOINT_STALE in reconcile(stale)
    assert ConflictKind.PROJECT_AUTHORITY_UNAVAILABLE in reconcile(epoch(project_available=False))
    assert ConflictKind.FORBIDDEN_PROJECT_IDENTITY in reconcile(epoch(project_number=6))


def test_multiple_and_unknown_lineages_fail_closed() -> None:
    multiple = LineageSnapshot(
        identity("branch", "feature/other"),
        465,
        LineageClassification.CANONICAL,
        "feature/other",
        "rebuild/v2-foundation",
        "base-1",
        None,
    )
    unknown = LineageSnapshot(
        identity("branch", "feature/unknown"),
        465,
        LineageClassification.UNKNOWN,
        "feature/unknown",
        "rebuild/v2-foundation",
        "base-1",
        "head-1",
    )
    conflicts = reconcile(epoch(lineages=(lineage(), multiple, unknown)))
    assert ConflictKind.MULTIPLE_ACTIVE_LINEAGES in conflicts
    assert ConflictKind.UNKNOWN_LINEAGE in conflicts


def test_design_blob_and_unexplained_head_mismatch_fail_closed() -> None:
    design = CanonicalDesignSnapshot(identity("blob", "design"), "design.md", "old", "new", 465)
    changed = LineageSnapshot(
        identity("branch", "feature/supervisor"),
        465,
        LineageClassification.CANONICAL,
        "feature/supervisor",
        "rebuild/v2-foundation",
        "base-1",
        "head-1",
        "base-1",
        "head-1",
        "head-1",
        "head-1",
        False,
    )
    conflicts = reconcile(epoch(canonical_designs=(design,), lineages=(changed,)))
    assert ConflictKind.CANONICAL_DESIGN_MISMATCH in conflicts
    assert ConflictKind.UNEXPLAINED_SHA_CHANGE in conflicts


def test_base_checkpoint_ci_and_review_mismatches_fail_closed() -> None:
    inconsistent = LineageSnapshot(
        identity("branch", "feature/supervisor"),
        465,
        LineageClassification.CANONICAL,
        "feature/supervisor",
        "rebuild/v2-foundation",
        "base-new",
        "head-new",
        "base-old",
        "head-old",
        "ci-old",
        "review-old",
    )
    conflicts = reconcile(epoch(lineages=(inconsistent,)))
    assert ConflictKind.BASE_SHA_MISMATCH in conflicts
    assert ConflictKind.HEAD_SHA_MISMATCH in conflicts
    assert ConflictKind.CI_HEAD_MISMATCH in conflicts
    assert ConflictKind.REVIEW_HEAD_MISMATCH in conflicts
