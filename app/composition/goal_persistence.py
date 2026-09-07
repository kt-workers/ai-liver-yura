"""目標の確定と保存確認を分け、復元は目標所有者の検査を通す。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.domain.contracts.common import require_identifier
from app.domain.executive import CommittedExecutiveDecision
from app.domain.goals import GoalCommitmentSnapshot, GoalCommitmentStore
from app.domain.goals.contracts import GoalCommitmentCommitResult
from app.infrastructure.persistence import (
    DurabilityReceipt,
    DurabilityStatus,
    PersistenceError,
    PersistenceFailureCode,
    PostgresPersistenceRuntime,
)
from app.infrastructure.persistence.goal_snapshot_codec import OWNER_ID


@dataclass(frozen=True, slots=True)
class GoalPersistenceCommitResult:
    committed: GoalCommitmentCommitResult
    durability: asyncio.Future[DurabilityReceipt]


class CoreGoalPersistenceBinding:
    """保存機構の運転状態と、現在の目標状態を混同せずに接続する。"""

    def __init__(
        self,
        store: GoalCommitmentStore,
        persistence: PostgresPersistenceRuntime,
        *,
        runtime_epoch: str,
        restore_failure: PersistenceFailureCode | None = None,
    ) -> None:
        require_identifier(runtime_epoch, "runtime_epoch")
        if not isinstance(store, GoalCommitmentStore):
            raise ValueError("目標所有者にはGoalCommitmentStoreを指定してください")
        if not isinstance(persistence, PostgresPersistenceRuntime):
            raise ValueError("保存実行基盤にはPostgresPersistenceRuntimeを指定してください")
        if restore_failure is not None and not isinstance(restore_failure, PersistenceFailureCode):
            raise ValueError("復元失敗は型付きの保存失敗分類で指定してください")
        self._store = store
        self._persistence = persistence
        self._runtime_epoch = runtime_epoch
        self._restore_failure = restore_failure

    @classmethod
    async def restore(
        cls,
        persistence: PostgresPersistenceRuntime,
        *,
        runtime_epoch: str,
    ) -> CoreGoalPersistenceBinding:
        require_identifier(runtime_epoch, "runtime_epoch")
        restored = await persistence.restore_goals()
        store = GoalCommitmentStore(restored.value)
        return cls(
            store, persistence, runtime_epoch=runtime_epoch, restore_failure=restored.failure_code
        )

    @property
    def restore_failure(self) -> PersistenceFailureCode | None:
        return self._restore_failure

    def snapshot(self) -> GoalCommitmentSnapshot:
        return self._store.snapshot()

    def apply(self, decision: CommittedExecutiveDecision) -> GoalPersistenceCommitResult:
        loop = asyncio.get_running_loop()
        committed = self._store.apply(decision)
        request_id = f"{self._runtime_epoch}:goals:{committed.snapshot.revision}"
        try:
            durability = self._persistence.persist_goals(
                committed.snapshot,
                request_id=request_id,
                runtime_epoch=self._runtime_epoch,
            )
        except (PersistenceError, ValueError) as error:
            code = (
                error.code
                if isinstance(error, PersistenceError)
                else PersistenceFailureCode.CONSTRAINT_VIOLATION
            )
            durability = loop.create_future()
            durability.set_result(
                DurabilityReceipt(
                    request_id,
                    OWNER_ID,
                    committed.snapshot.revision,
                    request_id,
                    DurabilityStatus.FAILED,
                    failure_code=code,
                )
            )
        return GoalPersistenceCommitResult(committed, durability)
