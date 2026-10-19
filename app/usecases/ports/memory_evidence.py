"""判断が必要とする記憶の現在公開だけを受け取る接続口。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from app.domain.contracts.persistence import PersistenceOperationResult

if TYPE_CHECKING:
    from app.domain.contracts.finalization import AuthorityReadPublication
    from app.domain.memory import MemoryRetrievalQuery
    from app.domain.memory.ranking import RankedMemoryEvidenceView
    from app.domain.memory.semantic_assertions import MemorySemanticAssertionEntry


class MemoryEvidencePort(Protocol):
    """意味・現在世代・取消後の回収は接続済みの既存所有者が維持する。"""

    async def read_retrieval_publication(
        self, query: MemoryRetrievalQuery
    ) -> PersistenceOperationResult[AuthorityReadPublication[RankedMemoryEvidenceView]]:
        ...

    async def read_semantic_assertion_publication(
        self, memory_id: str, expected_revision: int | None = None
    ) -> PersistenceOperationResult[AuthorityReadPublication[MemorySemanticAssertionEntry]]:
        ...
