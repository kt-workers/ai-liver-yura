"""記憶ユースケースから保存側へ依頼する操作契約。DBやSDKの型は含めない。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from app.domain.contracts.persistence import PersistenceOperationResult

if TYPE_CHECKING:
    from app.domain.contracts.finalization import AuthorityReadPublication
    from app.domain.memory import MemoryWriteRequest, MemoryWriteResult
    from app.domain.memory.contracts import MemoryRetrievalQuery
    from app.domain.memory.ranking import RankedMemoryEvidenceView
    from app.domain.memory.semantic_assertions import MemorySemanticAssertionEntry


@runtime_checkable
class MemoryPersistencePort(Protocol):
    """意味の正本を維持して既存の保存Ownerへ配送する。資源の開閉は要求しない。"""

    async def write_memory(
        self, request: MemoryWriteRequest
    ) -> PersistenceOperationResult[MemoryWriteResult]: ...

    async def retrieve_memory(
        self, query: MemoryRetrievalQuery
    ) -> PersistenceOperationResult[RankedMemoryEvidenceView]: ...

    async def read_memory_retrieval_publication(
        self, query: MemoryRetrievalQuery
    ) -> PersistenceOperationResult[AuthorityReadPublication[RankedMemoryEvidenceView]]: ...

    async def read_memory_semantic_assertion(
        self, memory_id: str, expected_revision: int | None = None
    ) -> PersistenceOperationResult[MemorySemanticAssertionEntry]: ...

    async def read_memory_semantic_assertion_publication(
        self, memory_id: str, expected_revision: int | None = None
    ) -> PersistenceOperationResult[AuthorityReadPublication[MemorySemanticAssertionEntry]]: ...
