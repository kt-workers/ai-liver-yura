"""実際の目標所有者を使い、DB固有クラスなしで復元・確定・保存確認を検証する。"""

from __future__ import annotations

import asyncio

import pytest

from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
from app.domain.contracts.persistence import (
    GOAL_PERSISTENCE_OWNER_ID,
    DurabilityReceipt,
    DurabilityStatus,
    PersistenceError,
    PersistenceFailureCode,
    PersistenceOperationResult,
)
from app.domain.executive import GoalTransitionOperation
from app.domain.goals import GoalCommitmentSnapshot, GoalCommitmentStore
from app.infrastructure.persistence.goal_binding import CoreGoalPersistenceBinding as LegacyBinding
from app.usecases.goal_persistence import CoreGoalPersistenceBinding
from app.usecases.ports.goal_persistence import GoalPersistencePort
from tests.domain.goals.test_goal_commitment_store import decision, goal_transition


class Backend:
    """復元と保存受付だけを実装する。起動・DB・プール等を持ち込まない。"""

    def __init__(self, restore_failure: PersistenceFailureCode | None = None) -> None:
        self.restore_failure = restore_failure
        self.fail_save = False
        self.snapshots: list[GoalCommitmentSnapshot] = []
        self.receipts: list[asyncio.Future[DurabilityReceipt]] = []

    async def restore_goals(self) -> PersistenceOperationResult[GoalCommitmentSnapshot]:
        return PersistenceOperationResult(None, self.restore_failure)

    def persist_goals(
        self, snapshot: GoalCommitmentSnapshot, *, request_id: str, runtime_epoch: str,
    ) -> asyncio.Future[DurabilityReceipt]:
        if self.fail_save:
            raise PersistenceError(PersistenceFailureCode.CONNECTION_FAILED, "試験用保存失敗")
        self.snapshots.append(snapshot)
        result: asyncio.Future[DurabilityReceipt] = asyncio.get_running_loop().create_future()
        self.receipts.append(result)
        return result


def test_public_binding_identity_is_preserved() -> None:
    assert LegacyBinding is CoreGoalPersistenceBinding
    assert isinstance(Backend(), GoalPersistencePort)


@pytest.mark.asyncio
async def test_domain_commit_is_separate_from_pending_durability() -> None:
    backend = Backend()
    binding = await CoreGoalPersistenceBinding.restore(backend, runtime_epoch="epoch")
    result = binding.apply(
        decision("create", 0, goals=(goal_transition(GoalTransitionOperation.CREATE, 0),))
    )
    try:
        assert binding.snapshot() == result.committed.snapshot
        assert backend.snapshots == [result.committed.snapshot]
        assert result.durability is backend.receipts[0]
        assert not result.durability.done()
        assert binding.snapshot().goals[0].goal_id == "goal-1"
    finally:
        for receipt in backend.receipts:
            receipt.cancel()


@pytest.mark.asyncio
@pytest.mark.parametrize("restore_failed", [False, True])
async def test_persistence_failure_does_not_undo_domain_commit(restore_failed: bool) -> None:
    backend = Backend(PersistenceFailureCode.CONNECTION_FAILED if restore_failed else None)
    backend.fail_save = not restore_failed
    binding = await CoreGoalPersistenceBinding.restore(backend, runtime_epoch="epoch")
    result = binding.apply(
        decision("create", 0, goals=(goal_transition(GoalTransitionOperation.CREATE, 0),))
    )
    receipt = await result.durability
    assert binding.snapshot() == result.committed.snapshot
    assert binding.snapshot().goals[0].goal_id == "goal-1"
    assert receipt.status is DurabilityStatus.FAILED
    assert receipt.failure_code is PersistenceFailureCode.CONNECTION_FAILED
    assert receipt.owner_id == GOAL_PERSISTENCE_OWNER_ID
    assert receipt.owner_state_revision == result.committed.snapshot.revision
    assert backend.snapshots == []


def test_non_backend_is_rejected_before_use() -> None:
    store = GoalCommitmentStore(bounds=V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)
    with pytest.raises(ValueError, match="GoalPersistencePort"):
        CoreGoalPersistenceBinding(store, object(), runtime_epoch="epoch")  # type: ignore[arg-type]
