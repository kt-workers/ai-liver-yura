from tools.loop_engine.ci_gate import (
    CIGateStatus,
    CIObservation,
)
from tools.loop_engine.ci_gate import (
    evaluate_exact_head as ci_gate,
)
from tools.loop_engine.review_gate import (
    ReviewEvidence,
    ReviewGateStatus,
)
from tools.loop_engine.review_gate import (
    evaluate_exact_head as review_gate,
)


def test_ci_gate_requires_success_for_exact_head() -> None:
    assert ci_gate("head", CIObservation("head", "success")) is CIGateStatus.PASS
    assert ci_gate("head", CIObservation("old", "success")) is CIGateStatus.STALE
    assert ci_gate("head", None) is CIGateStatus.YIELD_EXTERNAL


def test_ci_gate_rejects_old_head_before_pending_classification() -> None:
    assert ci_gate("head", CIObservation("old", None)) is CIGateStatus.STALE
    assert ci_gate("head", CIObservation("old", "queued")) is CIGateStatus.STALE
    assert ci_gate("head", CIObservation("old", "in_progress")) is CIGateStatus.STALE
    assert ci_gate("head", CIObservation("head", "queued")) is CIGateStatus.YIELD_EXTERNAL
    assert ci_gate("head", CIObservation("head", "in_progress")) is CIGateStatus.YIELD_EXTERNAL


def test_review_gate_requires_fresh_zero_blocking_pass() -> None:
    assert review_gate("head", ReviewEvidence("head", "PASS", 0)) is ReviewGateStatus.PASS
    assert review_gate("head", ReviewEvidence("head", "PASS", 1)) is ReviewGateStatus.NOT_RUN
    assert review_gate("head", ReviewEvidence("old", "PASS", 0)) is ReviewGateStatus.STALE
