from tools.loop_engine.models import (
    LineageClassification,
    LineageSnapshot,
    MissionSnapshot,
    RunDisposition,
)
from tools.loop_engine.supervisor import MissionSupervisor

from .conftest import epoch, identity, lineage, work


def test_resume_pass_creates_complete_secret_safe_task_packet() -> None:
    decision = MissionSupervisor().decide(epoch())
    packet = decision.task_packet
    assert decision.disposition is RunDisposition.CONTINUE
    assert decision.resume_certificate.gate == "PASS"
    assert packet is not None
    assert all((packet.authority, packet.scope, packet.non_goals, packet.exact_target))
    assert all((packet.dependencies, packet.acceptance_checks, packet.risk_boundary))
    assert "test-secret-value" not in repr(packet)


def test_resume_stop_never_creates_task_packet() -> None:
    decision = MissionSupervisor().decide(
        epoch(mission=MissionSnapshot(identity("issue", "450"), 465, True))
    )
    assert decision.resume_certificate.gate == "STOP"
    assert decision.task_packet is None


def test_duplicate_wait_and_false_mission_complete_are_yield_external() -> None:
    first = MissionSupervisor().decide(epoch())
    assert first.task_packet is not None
    duplicate = MissionSupervisor().decide(
        epoch(checkpoint_schedule_keys=(first.task_packet.schedule_key,))
    )
    empty = MissionSupervisor().decide(
        epoch(mission=MissionSnapshot(identity("issue", "450"), None), works=())
    )
    assert duplicate.duplicate_suppressed
    assert duplicate.disposition is RunDisposition.YIELD_EXTERNAL
    assert empty.disposition is RunDisposition.YIELD_EXTERNAL


def test_only_root_completion_evidence_allows_mission_complete() -> None:
    decision = MissionSupervisor().decide(
        epoch(mission=MissionSnapshot(identity("issue", "450"), None, False, True), works=())
    )
    assert decision.disposition is RunDisposition.MISSION_COMPLETE


def test_unrelated_work_conflict_does_not_block_independent_actionable_work() -> None:
    blocked = work(466, priority="P0")
    independent = work(467, priority="P1", status="Ready")
    unknown = LineageSnapshot(
        identity("branch", "feature/unknown"),
        466,
        LineageClassification.UNKNOWN,
        "feature/unknown",
        "rebuild/v2-foundation",
        "base-1",
        "head-1",
    )
    decision = MissionSupervisor().decide(
        epoch(
            mission=MissionSnapshot(identity("issue", "450"), 466),
            works=(blocked, independent),
            lineages=(lineage(), unknown),
        )
    )
    assert decision.disposition is RunDisposition.CONTINUE
    assert decision.selected_work_id == 467
    assert decision.resume_certificate.gate == "PASS"
