"""記憶要求を既存Ownerへ配送する。具体的な保存基盤は構成側から受け取る。"""

from __future__ import annotations

from app.domain.contracts.finalization import AuthorityReadPublication
from app.domain.contracts.persistence import PersistenceOperationResult
from app.domain.memory import MemoryRelationKind, MemoryWriteRequest, MemoryWriteResult
from app.domain.memory.contracts import MemoryRetrievalQuery
from app.domain.memory.ranking import RankedMemoryEvidenceView
from app.domain.memory.semantic_assertions import MemorySemanticAssertionEntry
from app.domain.memory_reflection import ReflectionCandidateResult
from app.usecases.persistence_tasks import BoundedPersistenceWorkOwner, CoreMemoryOperation
from app.usecases.ports.memory_persistence import MemoryPersistencePort


class CoreMemoryPersistenceBinding(BoundedPersistenceWorkOwner):
    """記憶操作の型と配送だけを扱い、意味の判断と保存結果を代行しない。"""

    def __init__(self, persistence: MemoryPersistencePort, *, max_pending: int) -> None:
        if not isinstance(persistence, MemoryPersistencePort):
            raise ValueError("記憶保存にはMemoryPersistencePortを満たす実行基盤が必要です")
        self._persistence = persistence
        super().__init__(max_pending=max_pending)

    def submit_write(self, request: MemoryWriteRequest) -> CoreMemoryOperation[MemoryWriteResult]:
        if not isinstance(request, MemoryWriteRequest):
            raise ValueError("記憶書込みには型付き要求が必要です")
        return self._submit(lambda: self._persistence.write_memory(request))

    def submit_reflection(
        self,
        result: ReflectionCandidateResult,
        *,
        expected_revision: int | None = None,
        target_memory_id: str | None = None,
        relation_kind: MemoryRelationKind | None = None,
    ) -> CoreMemoryOperation[MemoryWriteResult] | None:
        if not isinstance(result, ReflectionCandidateResult):
            raise ValueError("振り返り所有者の型付き結果が必要です")
        if result.candidate is None:
            return None
        return self.submit_write(
            MemoryWriteRequest(result.candidate, expected_revision, target_memory_id, relation_kind)
        )

    def submit_retrieval(
        self, query: MemoryRetrievalQuery
    ) -> CoreMemoryOperation[RankedMemoryEvidenceView]:
        if not isinstance(query, MemoryRetrievalQuery):
            raise ValueError("記憶検索には型付き要求が必要です")
        return self._submit(lambda: self._persistence.retrieve_memory(query))

    def submit_retrieval_publication(
        self, query: MemoryRetrievalQuery
    ) -> CoreMemoryOperation[AuthorityReadPublication[RankedMemoryEvidenceView]]:
        """検索集合の現在公開を同じ保存Ownerへ配送する。"""
        if not isinstance(query, MemoryRetrievalQuery):
            raise ValueError("記憶検索には型付き要求が必要です")
        return self._submit(lambda: self._persistence.read_memory_retrieval_publication(query))

    async def read_retrieval_publication(
        self, query: MemoryRetrievalQuery
    ) -> PersistenceOperationResult[AuthorityReadPublication[RankedMemoryEvidenceView]]:
        return await self.submit_retrieval_publication(query).wait()

    def submit_semantic_assertion_read(
        self, memory_id: str, expected_revision: int | None = None
    ) -> CoreMemoryOperation[MemorySemanticAssertionEntry]:
        return self._submit(
            lambda: self._persistence.read_memory_semantic_assertion(memory_id, expected_revision)
        )

    def submit_semantic_assertion_publication(
        self, memory_id: str, expected_revision: int | None = None
    ) -> CoreMemoryOperation[AuthorityReadPublication[MemorySemanticAssertionEntry]]:
        return self._submit(
            lambda: self._persistence.read_memory_semantic_assertion_publication(
                memory_id, expected_revision
            )
        )

    async def read_semantic_assertion_publication(
        self, memory_id: str, expected_revision: int | None = None
    ) -> PersistenceOperationResult[AuthorityReadPublication[MemorySemanticAssertionEntry]]:
        """同じ保存Ownerの公開を待ち、取消時も投入済み操作を回収する。"""
        return await self.submit_semantic_assertion_publication(memory_id, expected_revision).wait()
