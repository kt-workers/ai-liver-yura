from __future__ import annotations

from dataclasses import replace

from tools.loop_engine.models import RunDisposition
from tools.loop_engine.operational_store import PostgreSQLOperationalStore, StoreStatus
from tools.loop_engine.runner import (
    ExecutionEvidence,
    ExecutionStatus,
    LoopRunner,
    VerificationEvidence,
)
from tools.loop_engine.supervisor import MissionSupervisor

from .conftest import epoch


class Observer:
    def __init__(self) -> None:
        self.calls = 0

    def observe(self):  # type: ignore[no-untyped-def]
        self.calls += 1
        return epoch()


class Executor:
    def execute(self, packet):  # type: ignore[no-untyped-def]
        return ExecutionEvidence(ExecutionStatus.COMPLETED, "head", "CODEX_EXITED")


class Verifier:
    def verify(self, packet, execution):  # type: ignore[no-untyped-def]
        return VerificationEvidence(True, "head", "EXACT_HEAD_CI_SUCCESS")


class Checkpoints:
    def __init__(self) -> None:
        self.events: list[str] = []

    def publish(self, decision, result):  # type: ignore[no-untyped-def]
        self.events.append(result)


class Cursor:
    def execute(self, query, parameters):  # type: ignore[no-untyped-def]
        return None


class Connection:
    def cursor(self) -> Cursor:
        return Cursor()

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None


def test_runner_executes_one_transition_checkpoints_and_selects_next_work() -> None:
    observer = Observer()
    checkpoints = Checkpoints()
    result = LoopRunner(
        observer,
        MissionSupervisor(),
        Executor(),
        Verifier(),
        checkpoints,
        PostgreSQLOperationalStore(Connection),
    ).run_once()

    assert result.execution is not None
    assert result.verification is not None and result.verification.passed
    assert result.checkpoint_published
    assert result.operational_store_status is StoreStatus.STORED
    assert observer.calls == 2
    assert checkpoints.events == ["VERIFIED"]


def test_runner_rejects_verification_for_a_different_execution_head() -> None:
    class MismatchedVerifier:
        def verify(self, packet, execution):  # type: ignore[no-untyped-def]
            return VerificationEvidence(True, "other-head", "EXACT_HEAD_CI_SUCCESS")

    observer = Observer()
    checkpoints = Checkpoints()
    result = LoopRunner(
        observer,
        MissionSupervisor(),
        Executor(),
        MismatchedVerifier(),
        checkpoints,
        PostgreSQLOperationalStore(Connection),
    ).run_once()

    assert result.disposition is RunDisposition.INTERVENTION_REQUIRED
    assert result.execution is not None and result.execution.observed_head_sha == "head"
    assert result.verification is not None and result.verification.exact_head_sha == "other-head"
    assert result.operational_store_status is None
    assert observer.calls == 1
    assert checkpoints.events == ["VERIFICATION_HEAD_MISMATCH"]


def test_runner_rejects_verification_when_execution_head_is_missing() -> None:
    class MissingHeadExecutor:
        def execute(self, packet):  # type: ignore[no-untyped-def]
            return ExecutionEvidence(ExecutionStatus.COMPLETED, None, "CODEX_EXITED")

    observer = Observer()
    checkpoints = Checkpoints()
    result = LoopRunner(
        observer,
        MissionSupervisor(),
        MissingHeadExecutor(),
        Verifier(),
        checkpoints,
    ).run_once()

    assert result.disposition is RunDisposition.INTERVENTION_REQUIRED
    assert result.operational_store_status is None
    assert observer.calls == 1
    assert checkpoints.events == ["VERIFICATION_HEAD_MISMATCH"]


def test_runner_yields_without_executor_for_wait_only_decision() -> None:
    class WaitingObserver(Observer):
        def observe(self):  # type: ignore[no-untyped-def]
            current = epoch()
            waiting = replace(current.works[0], actionable=False, wait_only=True)
            return replace(current, works=(waiting,))

    result = LoopRunner(
        WaitingObserver(), MissionSupervisor(), Executor(), Verifier(), Checkpoints()
    ).run_once()

    assert result.disposition is RunDisposition.YIELD_EXTERNAL
    assert result.execution is None
