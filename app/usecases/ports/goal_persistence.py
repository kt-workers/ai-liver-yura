"""目標所有者の復元候補と、確定後の保存確認を仲介する契約。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from app.domain.contracts.persistence import DurabilityReceipt, PersistenceOperationResult

if TYPE_CHECKING:
    from app.domain.goals.contracts import GoalCommitmentSnapshot


@runtime_checkable
class GoalPersistencePort(Protocol):
    """現在目標の意味・確定権限を保存基盤へ渡さず、既存の状態を搬送する。"""

    async def restore_goals(self) -> PersistenceOperationResult[GoalCommitmentSnapshot]: ...

    def persist_goals(
        self,
        snapshot: GoalCommitmentSnapshot,
        *,
        request_id: str,
        runtime_epoch: str,
    ) -> asyncio.Future[DurabilityReceipt]: ...
