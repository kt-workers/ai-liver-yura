from app.operations.mission_supervisor import (
    CanonicalDesignSnapshot,
    ConflictKind,
    LineageClassification,
    LineageSnapshot,
    MissionSnapshot,
    MissionSupervisor,
    ObservationEpoch,
    RunDisposition,
    SourceIdentity,
    WorkSnapshot,
    WriteIntent,
)


def identity(kind: str, stable_id: str) -> SourceIdentity:
    return SourceIdentity(kind, stable_id, "rev-1")


def work(
    number: int = 465,
    *,
    priority: str = "P0",
    actionable: bool = True,
    wait_only: bool = False,
    wait_reason: str | None = None,
    status: str = "In progress",
) -> WorkSnapshot:
    return WorkSnapshot(
        identity("issue", str(number)),
        number,
        True,
        status,
        priority,
        True,
        True,
        actionable,
        wait_only,
        wait_reason,
    )


def lineage(
    *,
    classification: LineageClassification = LineageClassification.CANONICAL,
    head: str = "head-1",
) -> LineageSnapshot:
    return LineageSnapshot(
        identity("branch", "feature/supervisor"),
        465,
        classification,
        "feature/supervisor",
        "rebuild/v2-foundation",
        "base-1",
        head,
        "base-1",
        head,
        head,
        head,
    )


def epoch(
    *,
    observation_id: str = "epoch-1",
    project_number: int = 7,
    project_available: bool = True,
    mission: MissionSnapshot | None = None,
    works: tuple[WorkSnapshot, ...] | None = None,
    lineages: tuple[LineageSnapshot, ...] | None = None,
    canonical_designs: tuple[CanonicalDesignSnapshot, ...] | None = None,
    checkpoint_schedule_keys: tuple[str, ...] = (),
) -> ObservationEpoch:
    return ObservationEpoch(
        observation_id,
        "ktan514/ai-liver-yura",
        "rebuild/v2-foundation",
        "base-1",
        project_number,
        project_available,
        True,
        mission or MissionSnapshot(identity("issue", "450"), 465),
        works if works is not None else (work(),),
        lineages if lineages is not None else (lineage(),),
        canonical_designs
        if canonical_designs is not None
        else (
            CanonicalDesignSnapshot(
                identity("blob", "design"), "design.md", "blob-1", "blob-1", 465
            ),
        ),
        checkpoint_schedule_keys,
    )


def test_live_checkpoint_consistency_creates_continue_packet() -> None:
    decision = MissionSupervisor().decide(epoch())

    assert decision.disposition is RunDisposition.CONTINUE
    assert decision.resume_certificate.gate == "PASS"
    assert decision.task_packet is not None


def test_stale_mission_checkpoint_stops_without_task_packet() -> None:
    decision = MissionSupervisor().decide(
        epoch(mission=MissionSnapshot(identity("issue", "450"), 465, True))
    )

    assert ConflictKind.MISSION_CHECKPOINT_STALE in decision.resume_certificate.conflicts
    assert decision.resume_certificate.gate == "STOP"
    assert decision.task_packet is None


def test_multiple_canonical_lineages_and_unknown_lineage_fail_closed() -> None:
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
    conflicts = MissionSupervisor().reconcile(epoch(lineages=(lineage(), multiple, unknown)))

    assert ConflictKind.MULTIPLE_ACTIVE_LINEAGES in conflicts
    assert ConflictKind.UNKNOWN_LINEAGE in conflicts


def test_canonical_blob_mismatch_and_unexplained_head_change_are_conflicts() -> None:
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
    conflicts = MissionSupervisor().reconcile(
        epoch(canonical_designs=(design,), lineages=(changed,))
    )

    assert ConflictKind.CANONICAL_DESIGN_MISMATCH in conflicts
    assert ConflictKind.UNEXPLAINED_SHA_CHANGE in conflicts


def test_base_checkpoint_ci_and_review_identity_mismatches_fail_closed() -> None:
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
    conflicts = MissionSupervisor().reconcile(epoch(lineages=(inconsistent,)))

    assert ConflictKind.BASE_SHA_MISMATCH in conflicts
    assert ConflictKind.HEAD_SHA_MISMATCH in conflicts
    assert ConflictKind.CI_HEAD_MISMATCH in conflicts
    assert ConflictKind.REVIEW_HEAD_MISMATCH in conflicts


def test_project_seven_unavailable_and_project_six_are_hard_conflicts() -> None:
    supervisor = MissionSupervisor()

    assert ConflictKind.PROJECT_AUTHORITY_UNAVAILABLE in supervisor.reconcile(
        epoch(project_available=False)
    )
    assert ConflictKind.FORBIDDEN_PROJECT_IDENTITY in supervisor.reconcile(epoch(project_number=6))


def test_current_actionable_work_continues() -> None:
    other = work(500, priority="P0")
    decision = MissionSupervisor().decide(epoch(works=(work(465, priority="P2"), other)))

    assert decision.selected_work_id == 465


def test_review_pending_selects_independent_actionable_work() -> None:
    waiting = work(465, actionable=False, wait_only=True, wait_reason="review pending")
    independent = work(500, priority="P1", status="Ready")
    decision = MissionSupervisor().decide(epoch(works=(waiting, independent)))

    assert decision.disposition is RunDisposition.CONTINUE
    assert decision.selected_work_id == 500


def test_verification_pending_selects_independent_actionable_work() -> None:
    waiting = work(465, actionable=False, wait_only=True, wait_reason="verification pending")
    independent = work(500, priority="P1", status="Ready")
    decision = MissionSupervisor().decide(epoch(works=(waiting, independent)))

    assert decision.disposition is RunDisposition.CONTINUE
    assert decision.selected_work_id == 500


def test_priority_and_issue_number_are_deterministic_tie_breakers() -> None:
    p1 = work(600, priority="P1", status="Ready")
    p0_high_number = work(700, priority="P0", status="Ready")
    p0_low_number = work(500, priority="P0", status="Ready")
    selected = MissionSupervisor().decide(
        epoch(
            mission=MissionSnapshot(identity("issue", "450"), None),
            works=(p1, p0_high_number, p0_low_number),
        )
    )

    assert selected.selected_work_id == 500


def test_task_packet_contains_required_contract_and_no_secrets() -> None:
    packet = MissionSupervisor().decide(epoch()).task_packet

    assert packet is not None
    assert all(
        (packet.authority, packet.scope, packet.non_goals, packet.exact_target, packet.dependencies)
    )
    assert all((packet.acceptance_checks, packet.risk_boundary, packet.expected_next_transition))
    assert "test-secret-value" not in repr(packet)


def test_schedule_key_suppresses_duplicate_after_restart_checkpoint() -> None:
    supervisor = MissionSupervisor()
    first = supervisor.decide(epoch())
    assert first.task_packet is not None
    restarted = epoch(
        observation_id="epoch-2", checkpoint_schedule_keys=(first.task_packet.schedule_key,)
    )
    duplicate = supervisor.decide(restarted)

    assert duplicate.duplicate_suppressed
    assert duplicate.task_packet is None


def test_external_wait_yields_and_empty_candidates_do_not_complete_mission() -> None:
    waiting = work(465, actionable=False, wait_only=True)
    decision = MissionSupervisor().decide(epoch(works=(waiting,)))
    empty = MissionSupervisor().decide(
        epoch(mission=MissionSnapshot(identity("issue", "450"), None), works=())
    )

    assert decision.disposition is RunDisposition.YIELD_EXTERNAL
    assert empty.disposition is RunDisposition.YIELD_EXTERNAL


def test_only_root_completion_evidence_allows_mission_complete() -> None:
    decision = MissionSupervisor().decide(
        epoch(mission=MissionSnapshot(identity("issue", "450"), None, False, True), works=())
    )

    assert decision.disposition is RunDisposition.MISSION_COMPLETE


def test_write_gate_rejects_project_six_stale_head_stale_field_and_trunk() -> None:
    supervisor = MissionSupervisor()
    project_six = WriteIntent("i", "project", "6", "edit", (), (), "epoch")
    stale = WriteIntent("i", "project", "7", "edit", (("head", "old"),), (), "epoch")
    stale_field = WriteIntent(
        "i", "project", "7", "edit", (("field_id", "field-old"),), (), "epoch"
    )
    trunk = WriteIntent("i", "branch", "rebuild/v2-foundation", "content", (), (), "epoch")

    assert (
        supervisor.validate_write_gate(project_six, {}).conflict
        is ConflictKind.FORBIDDEN_PROJECT_IDENTITY
    )
    assert (
        supervisor.validate_write_gate(stale, {"head": "new"}).conflict
        is ConflictKind.STALE_WRITE_GATE
    )
    assert (
        supervisor.validate_write_gate(stale_field, {"field_id": "field-new"}).conflict
        is ConflictKind.STALE_WRITE_GATE
    )
    assert (
        supervisor.validate_write_gate(trunk, {}).conflict
        is ConflictKind.DIRECT_TRUNK_WRITE_FORBIDDEN
    )


def test_write_gate_requires_effect_readback_match() -> None:
    intent = WriteIntent(
        "i", "project", "7", "edit", (("head", "h"),), (("status", "Done"),), "epoch"
    )
    result = MissionSupervisor().validate_write_gate(
        intent, {"head": "h"}, {"status": "In progress"}
    )

    assert not result.allowed
    assert result.conflict is ConflictKind.MUTATION_EFFECT_MISMATCH
