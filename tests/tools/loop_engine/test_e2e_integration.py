from __future__ import annotations

from dataclasses import replace

from tools.loop_engine.integration import run_controlled_transition
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


class ScenarioObserver:
    def __init__(self) -> None:
        self.calls = 0

    def observe(self):  # type: ignore[no-untyped-def]
        self.calls += 1
        current = epoch(observation_id=f"epoch-{self.calls}")
        if self.calls == 2:
            completed = replace(current.works[0], actionable=False, wait_only=True)
            return replace(current, works=(completed,))
        return current


class ScenarioExecutor:
    def __init__(self) -> None:
        self.packet_ids: list[str] = []

    def execute(self, packet):  # type: ignore[no-untyped-def]
        self.packet_ids.append(packet.packet_id)
        return ExecutionEvidence(ExecutionStatus.COMPLETED, "head-1", "CODEX_PUSH_READBACK")


class ScenarioVerifier:
    def verify(self, packet, execution):  # type: ignore[no-untyped-def]
        assert execution.observed_head_sha == "head-1"
        return VerificationEvidence(True, "head-1", "EXACT_HEAD_CI_SUCCESS")


class ScenarioCheckpoints:
    def __init__(self) -> None:
        self.records: list[tuple[int | None, str]] = []

    def publish(self, decision, result):  # type: ignore[no-untyped-def]
        self.records.append((decision.selected_work_id, result))


class Cursor:
    def __init__(self) -> None:
        self.records: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, query, parameters):  # type: ignore[no-untyped-def]
        self.records.append((query, parameters))


class Connection:
    def __init__(self) -> None:
        self.cursor_value = Cursor()
        self.committed = False

    def cursor(self) -> Cursor:
        return self.cursor_value

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.committed = False

    def close(self) -> None:
        return None


def test_e2e_observe_select_execute_verify_checkpoint_store_and_next_selection() -> None:
    observer = ScenarioObserver()
    executor = ScenarioExecutor()
    checkpoints = ScenarioCheckpoints()
    connection = Connection()
    runner = LoopRunner(
        observer,
        MissionSupervisor(),
        executor,
        ScenarioVerifier(),
        checkpoints,
        PostgreSQLOperationalStore(lambda: connection),
    )
    result = run_controlled_transition(runner)

    assert executor.packet_ids
    assert result.verification is not None and result.verification.passed
    assert result.operational_store_status is StoreStatus.STORED
    assert checkpoints.records == [(465, "VERIFIED")]
    assert observer.calls == 2
    assert result.disposition is RunDisposition.YIELD_EXTERNAL
    assert connection.committed


def test_e2e_db_outage_keeps_github_checkpoint_path_safe() -> None:
    checkpoints = ScenarioCheckpoints()
    runner = LoopRunner(
        ScenarioObserver(),
        MissionSupervisor(),
        ScenarioExecutor(),
        ScenarioVerifier(),
        checkpoints,
        PostgreSQLOperationalStore(lambda: (_ for _ in ()).throw(OSError())),
    )
    result = run_controlled_transition(runner)

    assert result.operational_store_status is StoreStatus.DB_UNAVAILABLE
    assert checkpoints.records == [(465, "VERIFIED")]
