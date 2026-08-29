"""製品に依存せず、1回ごとの範囲を限定したLoop Engineering制御実行機。"""

from __future__ import annotations

import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .models import ObservationEpoch, RunDisposition, SupervisorDecision, TaskPacket
from .operational_store import PostgreSQLOperationalStore, StoreStatus
from .supervisor import MissionSupervisor


class ExecutionStatus(str, Enum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"


@dataclass(frozen=True, slots=True)
class ExecutionEvidence:
    status: ExecutionStatus
    observed_head_sha: str | None
    detail: str


@dataclass(frozen=True, slots=True)
class VerificationEvidence:
    passed: bool
    exact_head_sha: str | None
    detail: str


@dataclass(frozen=True, slots=True)
class RunnerResult:
    disposition: RunDisposition
    decision: SupervisorDecision
    execution: ExecutionEvidence | None
    verification: VerificationEvidence | None
    checkpoint_published: bool
    next_work_id: int | None
    operational_store_status: StoreStatus | None


class Observer(Protocol):
    def observe(self) -> ObservationEpoch: ...


class CodexExecutor(Protocol):
    def execute(self, packet: TaskPacket) -> ExecutionEvidence: ...


class Verifier(Protocol):
    def verify(self, packet: TaskPacket, execution: ExecutionEvidence) -> VerificationEvidence: ...


class CheckpointPublisher(Protocol):
    def publish(self, decision: SupervisorDecision, result: str) -> None: ...


class HeadResolver(Protocol):
    def resolve_head(self) -> str | None: ...


class SubprocessCodexExecutor:
    """固定引数だけで実行し、レビューワーやDBの秘密情報を境界外へ渡さない。"""

    def __init__(
        self,
        argv_prefix: Sequence[str],
        environment: Mapping[str, str],
        head_resolver: HeadResolver | None = None,
    ) -> None:
        self._argv_prefix = tuple(argv_prefix)
        self._environment = {
            key: value for key, value in environment.items() if key in {"PATH", "GH_TOKEN"}
        }
        self._head_resolver = head_resolver

    def execute(self, packet: TaskPacket) -> ExecutionEvidence:
        instruction = "\n".join(
            (
                f"作業パケット（TaskPacket）: {packet.packet_id}",
                f"対象範囲: {', '.join(packet.scope)}",
                f"厳密対象: {', '.join(packet.exact_target)}",
                f"受け入れ確認: {', '.join(packet.acceptance_checks)}",
            )
        )
        try:
            completed = subprocess.run(
                (*self._argv_prefix, instruction),
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=self._environment,
                timeout=1800,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ExecutionEvidence(
                ExecutionStatus.INTERRUPTED, None, "CODEX_EXECUTION_UNAVAILABLE"
            )
        if completed.returncode != 0:
            return ExecutionEvidence(ExecutionStatus.FAILED, None, "CODEX_EXITED")
        if self._head_resolver is None:
            return ExecutionEvidence(
                ExecutionStatus.INTERRUPTED, None, "EXECUTION_HEAD_READBACK_UNAVAILABLE"
            )
        try:
            observed_head_sha = self._head_resolver.resolve_head()
        except Exception:
            return ExecutionEvidence(
                ExecutionStatus.INTERRUPTED, None, "EXECUTION_HEAD_READBACK_UNAVAILABLE"
            )
        if not observed_head_sha:
            return ExecutionEvidence(
                ExecutionStatus.INTERRUPTED, None, "EXECUTION_HEAD_READBACK_UNAVAILABLE"
            )
        return ExecutionEvidence(ExecutionStatus.COMPLETED, observed_head_sha, "CODEX_EXITED")


class LoopRunner:
    """安全な遷移を1回実行し、その後に現在状態を1回だけ再観測する。"""

    def __init__(
        self,
        observer: Observer,
        supervisor: MissionSupervisor,
        executor: CodexExecutor,
        verifier: Verifier,
        checkpoints: CheckpointPublisher,
        store: PostgreSQLOperationalStore | None = None,
    ) -> None:
        self._observer = observer
        self._supervisor = supervisor
        self._executor = executor
        self._verifier = verifier
        self._checkpoints = checkpoints
        self._store = store

    def run_once(self) -> RunnerResult:
        decision = self._supervisor.decide(self._observer.observe())
        if decision.disposition is not RunDisposition.CONTINUE or decision.task_packet is None:
            self._checkpoints.publish(decision, decision.disposition.value)
            return RunnerResult(decision.disposition, decision, None, None, True, None, None)

        execution = self._executor.execute(decision.task_packet)
        if execution.status is not ExecutionStatus.COMPLETED:
            self._checkpoints.publish(decision, execution.detail)
            return RunnerResult(
                RunDisposition.YIELD_EXTERNAL, decision, execution, None, True, None, None
            )
        verification = self._verifier.verify(decision.task_packet, execution)
        if not verification.passed:
            self._checkpoints.publish(decision, verification.detail)
            return RunnerResult(
                RunDisposition.INTERVENTION_REQUIRED,
                decision,
                execution,
                verification,
                True,
                None,
                None,
            )
        if (
            execution.observed_head_sha is None
            or verification.exact_head_sha is None
            or verification.exact_head_sha != execution.observed_head_sha
        ):
            self._checkpoints.publish(decision, "VERIFICATION_HEAD_MISMATCH")
            return RunnerResult(
                RunDisposition.INTERVENTION_REQUIRED,
                decision,
                execution,
                verification,
                True,
                None,
                None,
            )
        store_status = self._record_transition(decision, verification)
        self._checkpoints.publish(decision, "VERIFIED")
        next_decision = self._supervisor.decide(self._observer.observe())
        return RunnerResult(
            next_decision.disposition,
            decision,
            execution,
            verification,
            True,
            next_decision.selected_work_id,
            store_status,
        )

    def _record_transition(
        self, decision: SupervisorDecision, verification: VerificationEvidence
    ) -> StoreStatus | None:
        if self._store is None or decision.task_packet is None:
            return None
        result = self._store.record(
            "loop_events",
            decision.task_packet.schedule_key,
            {
                "transition": "VERIFIED",
                "work_id": decision.selected_work_id,
                "exact_head_sha": verification.exact_head_sha,
            },
        )
        return result.status
