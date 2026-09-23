"""有界検索とOwnerの現在公開を判断根拠へ接続する。"""

from collections.abc import Callable
from dataclasses import dataclass

from app.composition.memory_persistence import CoreMemoryPersistenceBinding
from app.domain.attention import AttentionSource
from app.domain.contracts.common import freeze_json
from app.domain.contracts.finalization import AuthorityGenerationToken
from app.domain.executive import ExecutiveFactKind, ExecutiveFactRef
from app.domain.memory import MemoryRetrievalQuery
from app.domain.memory.ranking import RankedMemoryEvidenceView
from app.domain.memory.semantic_assertions import MemorySemanticAssertionEntry
from app.infrastructure.persistence import PersistenceError, PersistenceFailureCode


@dataclass(frozen=True, slots=True)
class CoreMemoryEvidenceConfiguration:
    """検索条件を信頼済み設定から受け取り、構成側で関連性を推測しない。"""

    query_for: Callable[[AttentionSource], MemoryRetrievalQuery]
    max_items: int
    max_estimated_tokens: int

    def __post_init__(self) -> None:
        if not callable(self.query_for):
            raise ValueError("記憶検索条件の明示供給元が必要です")
        if any(type(x) is not int or x < 1 for x in (self.max_items, self.max_estimated_tokens)):
            raise ValueError("記憶検索の上限が不正です")


class CoreMemoryEvidenceReader:
    def __init__(
        self, memory: CoreMemoryPersistenceBinding, config: CoreMemoryEvidenceConfiguration
    ) -> None:
        self.memory, self.config = memory, config
        self.latest_view: RankedMemoryEvidenceView | None = None
        self.latest_entries: tuple[MemorySemanticAssertionEntry, ...] = ()

    async def read(
        self, source: AttentionSource
    ) -> tuple[tuple[ExecutiveFactRef, ...], tuple[AuthorityGenerationToken, ...]]:
        query = self.config.query_for(source)
        if not isinstance(query, MemoryRetrievalQuery) or (
            query.max_items > self.config.max_items
            or query.max_estimated_tokens > self.config.max_estimated_tokens
        ):
            raise ValueError("記憶検索条件が起動時の上限を超えています")
        retrieved = await self.memory.submit_retrieval_publication(query).wait()
        if retrieved.failure_code is not None:
            raise PersistenceError(retrieved.failure_code, "判断根拠の記憶検索に失敗しました")
        if retrieved.value is None:
            raise PersistenceError(PersistenceFailureCode.UNAVAILABLE, "記憶検索結果がありません")
        retrieval_publication = retrieved.value
        view = retrieval_publication.value
        self.latest_view, self.latest_entries = view, ()
        if view.degraded:
            raise PersistenceError(PersistenceFailureCode.UNAVAILABLE, "記憶検索が機能低下中です")
        if not retrieval_publication.tokens:
            raise ValueError("記憶検索の現在公開にOwner tokenがありません")
        facts: list[ExecutiveFactRef] = []
        tokens: list[AuthorityGenerationToken] = list(retrieval_publication.tokens)
        for item in view.items:
            result = await self.memory.read_semantic_assertion_publication(
                item.memory_id, item.memory_revision
            )
            if result.failure_code is not None:
                raise PersistenceError(result.failure_code, "記憶の現在公開を取得できません")
            if result.value is None:
                raise PersistenceError(PersistenceFailureCode.UNAVAILABLE, "記憶の公開がありません")
            publication = result.value
            entry = publication.value
            self.latest_entries += (entry,)
            assertion = entry.assertion
            if assertion is None:
                # 未解決・古い記憶を事実へ昇格させず、Ownerの理由を保持する。
                continue
            if not publication.tokens:
                raise ValueError("記憶の現在公開にOwner tokenがありません")
            facts.append(ExecutiveFactRef(
                item.memory_id, ExecutiveFactKind.MEMORY_EVIDENCE, item.memory_revision,
                freeze_json({
                    "content": assertion.content.to_dict(),
                    "assertion_semantics": assertion.assertion_semantics.to_dict(),
                    "subject_identity": {
                        "kind": assertion.subject_identity.kind.value,
                        "subject_ref": assertion.subject_identity.subject_ref,
                    },
                    "provenance": [p.to_dict() for p in assertion.provenance],
                    "confidence": {
                        "value": assertion.confidence.value,
                        "basis": assertion.confidence.basis,
                    },
                    "temporal": {
                        "freshness": assertion.temporal.freshness.value,
                        "valid_from": None if assertion.temporal.valid_from is None
                        else assertion.temporal.valid_from.isoformat(),
                        "valid_until": None if assertion.temporal.valid_until is None
                        else assertion.temporal.valid_until.isoformat(),
                        "observed_at": None if assertion.temporal.observed_at is None
                        else assertion.temporal.observed_at.isoformat(),
                    },
                    "lifecycle": assertion.lifecycle.value,
                    "contradiction_refs": assertion.contradiction_refs,
                }),
            ))
            tokens.extend(publication.tokens)
        return tuple(facts), tuple(tokens)
